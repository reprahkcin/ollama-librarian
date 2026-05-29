import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "scripts" / "ollama-web-chat.py"


def load_app_module() -> types.ModuleType:
    env_keys = {
        "OLLAMA_WEB_HOST": "127.0.0.1",
        "OLLAMA_WEB_PORT": "8088",
        "OLLAMA_WEB_API_KEY": "",
    }
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-confidence-test-") as td:
        state_dir = Path(td)
        env_keys.update(
            {
                "OLLAMA_WEB_HISTORY_PATH": str(state_dir / "history.json"),
                "OLLAMA_WEB_STASH_PATH": str(state_dir / "stash.json"),
                "OLLAMA_WEB_PDF_INDEX_DB": str(state_dir / "pdf-rag.sqlite"),
                "OLLAMA_WEB_PDF_SOURCE": str(state_dir / "library"),
            }
        )

        previous = {k: os.environ.get(k) for k in env_keys}
        os.environ.update(env_keys)
        try:
            module_name = f"ollama_web_chat_confidence_test_{os.getpid()}_{id(state_dir)}"
            spec = importlib.util.spec_from_file_location(
                module_name, APP_PATH)
            if not spec or not spec.loader:
                raise RuntimeError(
                    "Failed to create import spec for ollama-web-chat.py"
                )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class ConfidenceCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app_module()

    def test_source_confidence_from_scores_can_emit_low(self):
        low_meta = self.app._source_confidence_from_scores(
            score=0.30,
            max_score=1.00,
            min_score=0.30,
            rank=3,
            total=3,
        )
        self.assertEqual(low_meta.get("confidence_label"), "Low")
        self.assertEqual(low_meta.get("confidence_class"), "conf-low")

    def test_annotate_citation_confidence_tight_range_uses_rank_buckets(self):
        citations = [
            {"path": "a.pdf", "location": 1, "score": 1.01},
            {"path": "b.pdf", "location": 2, "score": 0.98},
            {"path": "c.pdf", "location": 3, "score": 0.95},
            {"path": "d.pdf", "location": 4, "score": 0.92},
            {"path": "e.pdf", "location": 5, "score": 0.90},
        ]

        annotated = self.app._annotate_citation_confidence(citations)
        labels = [str(item.get("confidence_label")) for item in annotated]

        self.assertIn("High", labels)
        self.assertIn("Medium", labels)
        self.assertIn("Low", labels)

    def test_annotate_citation_confidence_non_tight_spread_emits_low(self):
        citations = [
            {"path": "a.pdf", "location": 1, "score": 1.00},
            {"path": "b.pdf", "location": 2, "score": 0.74},
            {"path": "c.pdf", "location": 3, "score": 0.40},
        ]

        annotated = self.app._annotate_citation_confidence(citations)
        by_path = {item.get("path"): item for item in annotated}

        self.assertEqual(
            by_path["a.pdf"].get("confidence_label"),
            "High",
        )
        self.assertEqual(
            by_path["b.pdf"].get("confidence_label"),
            "Medium",
        )
        self.assertEqual(
            by_path["c.pdf"].get("confidence_label"),
            "Low",
        )

    def test_annotate_citation_confidence_preserves_existing_values(self):
        citations = [
            {
                "path": "a.pdf",
                "location": 1,
                "score": 1.0,
                "confidence_label": "High",
                "confidence_class": "conf-high",
                "confidence_title": "precomputed",
            }
        ]

        annotated = self.app._annotate_citation_confidence(citations)
        self.assertEqual(annotated[0].get("confidence_label"), "High")
        self.assertEqual(annotated[0].get("confidence_class"), "conf-high")
        self.assertEqual(annotated[0].get("confidence_title"), "precomputed")


if __name__ == "__main__":
    unittest.main()
