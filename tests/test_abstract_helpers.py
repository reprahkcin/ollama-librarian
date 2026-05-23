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
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-abstract-test-") as td:
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
            module_name = f"ollama_web_chat_abstract_test_{os.getpid()}_{id(state_dir)}"
            spec = importlib.util.spec_from_file_location(module_name, APP_PATH)
            if not spec or not spec.loader:
                raise RuntimeError("Failed to create import spec for ollama-web-chat.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class AbstractHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app_module()

    def test_extract_json_object_handles_plain_and_wrapped_json(self):
        plain = self.app._extract_json_object('{"confidence": 88, "recommendation": "maybe"}')
        self.assertEqual(plain.get("confidence"), 88)

        wrapped = self.app._extract_json_object(
            'model output:\n{"confidence": 61, "recommendation": "skip"}\nthank you'
        )
        self.assertEqual(wrapped.get("recommendation"), "skip")

        invalid = self.app._extract_json_object("not-json")
        self.assertEqual(invalid, {})

    def test_clamp_confidence_bounds_and_default(self):
        self.assertEqual(self.app._clamp_confidence("91.7"), 92)
        self.assertEqual(self.app._clamp_confidence(-5), 0)
        self.assertEqual(self.app._clamp_confidence(120), 100)
        self.assertEqual(self.app._clamp_confidence("oops", default=42), 42)

    def test_confidence_bucket_thresholds(self):
        self.assertEqual(self.app._confidence_bucket(80), "High")
        self.assertEqual(self.app._confidence_bucket(55), "Moderate")
        self.assertEqual(self.app._confidence_bucket(54), "Low")

    def test_normalize_recommendation_with_direct_and_score_fallback(self):
        self.assertEqual(
            self.app._normalize_recommendation("download-and-index", 10),
            "download_and_index",
        )
        self.assertEqual(self.app._normalize_recommendation("reject", 90), "skip")
        self.assertEqual(self.app._normalize_recommendation("", 80), "download_and_index")
        self.assertEqual(self.app._normalize_recommendation("", 50), "maybe")
        self.assertEqual(self.app._normalize_recommendation("", 10), "skip")

    def test_recommendation_label_mapping(self):
        self.assertEqual(
            self.app._recommendation_label("download_and_index"),
            "Download and index",
        )
        self.assertEqual(self.app._recommendation_label("skip"), "Skip for now")
        self.assertEqual(
            self.app._recommendation_label("unknown"),
            "Maybe / needs manual review",
        )

    def test_extract_reason_list_from_list_string_and_fallback(self):
        from_list = self.app._extract_reason_list(["  strong signal  ", "second", "", "third", "fourth", "fifth"])
        self.assertEqual(from_list, ["strong signal", "second", "third", "fourth"])

        from_string = self.app._extract_reason_list("one; two\nthree; four; five")
        self.assertEqual(from_string, ["one", "two", "three", "four"])

        fallback = self.app._extract_reason_list([], fallback_text="First sentence. Second sentence! Third sentence? Fourth sentence.")
        self.assertEqual(fallback, ["First sentence.", "Second sentence!", "Third sentence?"])


if __name__ == "__main__":
    unittest.main()
