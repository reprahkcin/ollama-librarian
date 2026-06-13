import json
import importlib.util
import os
import types
import sqlite3
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEXER_PATH = REPO_ROOT / "src" / "ollama_librarian" / "indexer.py"


def load_indexer_module() -> types.ModuleType:
    module_name = f"ollama_librarian_indexer_test_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, INDEXER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to create import spec for indexer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.indexer = load_indexer_module()

    def test_retrieve_top_chunks_filtered_emits_trace_shape(self):
        conn = sqlite3.connect(":memory:")

        original_loader = self.indexer.load_all_chunks
        try:
            self.indexer.load_all_chunks = lambda _conn: [
                (
                    "doc-a.pdf",
                    "Doc A",
                    3,
                    "Herbert Hoover policy response in the Great Depression",
                    json.dumps([1.0, 0.0]),
                ),
                (
                    "doc-b.pdf",
                    "Doc B",
                    1,
                    "Completely unrelated text",
                    json.dumps([0.1, 0.0]),
                ),
            ]

            trace = []
            top = self.indexer.retrieve_top_chunks_filtered(
                conn,
                [1.0, 0.0],
                2,
                "Herbert Hoover policy response",
                None,
                None,
                trace_out=trace,
            )
        finally:
            self.indexer.load_all_chunks = original_loader
            conn.close()

        self.assertEqual(len(top), 2)
        self.assertEqual(len(trace), 2)

        first = trace[0]
        self.assertIn("rank", first)
        self.assertIn("path", first)
        self.assertIn("location", first)
        self.assertIn("vector_score", first)
        self.assertIn("lexical_path_title_score", first)
        self.assertIn("lexical_chunk_score", first)
        self.assertIn("entity_alignment_score", first)
        self.assertIn("semantic_drift_penalty", first)
        self.assertIn("final_score", first)

        expected_final = (
            first["vector_score"]
            + first["lexical_path_title_score"]
            + first["lexical_chunk_score"]
            + first["entity_alignment_score"]
            + first["semantic_drift_penalty"]
        )
        self.assertAlmostEqual(first["final_score"], expected_final, places=6)

    def test_retrieve_top_chunks_filtered_without_trace_out(self):
        conn = sqlite3.connect(":memory:")

        original_loader = self.indexer.load_all_chunks
        try:
            self.indexer.load_all_chunks = lambda _conn: [
                (
                    "doc-a.pdf",
                    "Doc A",
                    2,
                    "Great Depression context",
                    json.dumps([1.0, 0.0]),
                )
            ]

            top = self.indexer.retrieve_top_chunks_filtered(
                conn,
                [1.0, 0.0],
                1,
                "Great Depression",
                None,
                None,
            )
        finally:
            self.indexer.load_all_chunks = original_loader
            conn.close()

        self.assertEqual(len(top), 1)
        score, path, page, text = top[0]
        self.assertIsInstance(score, float)
        self.assertEqual(path, "doc-a.pdf")
        self.assertEqual(page, 2)
        self.assertIn("Depression", text)

    def test_format_ollama_http_error_for_gpu_runtime_failure(self):
        message = self.indexer._format_ollama_http_error(
            "/api/generate",
            500,
            '{"error":"an error was encountered while running the model: CUDA error\\nCUDA error: an illegal instruction was encountered"}',
        )

        self.assertIn("GPU/CUDA", message)
        self.assertIn("smaller model", message)
        self.assertIn("HTTP 500", message)

    def test_extract_ollama_error_text_prefers_json_error_field(self):
        detail = '{"error":"backend overloaded"}'
        text = self.indexer._extract_ollama_error_text(detail)
        self.assertEqual(text, "backend overloaded")

    def test_candidate_answer_models_prioritizes_primary_and_dedupes(self):
        models = self.indexer._candidate_answer_models(
            "qwen2.5:14b",
            ["qwen2.5:7b", "qwen2.5:14b", "qwen2.5:3b"],
            available_models=None,
            pressure_level="normal",
        )
        self.assertEqual(models, ["qwen2.5:14b", "qwen2.5:7b", "qwen2.5:3b"])

    def test_candidate_answer_models_filters_by_available_models(self):
        models = self.indexer._candidate_answer_models(
            "qwen2.5:14b",
            ["qwen2.5:7b", "llama3.2:3b"],
            available_models=["qwen2.5:7b", "llama3.2:3b"],
            pressure_level="normal",
        )
        # Primary is retained first for explicit user choice, then available fallbacks.
        self.assertEqual(models, ["qwen2.5:14b", "qwen2.5:7b", "llama3.2:3b"])

    def test_candidate_answer_models_keeps_primary_first_on_high_pressure(self):
        models = self.indexer._candidate_answer_models(
            "qwen2.5:14b",
            ["qwen2.5:7b", "qwen2.5:3b", "llama3.2:1b"],
            available_models=None,
            pressure_level="high",
        )
        self.assertEqual(
            models, ["qwen2.5:14b", "qwen2.5:7b", "qwen2.5:3b", "llama3.2:1b"])


if __name__ == "__main__":
    unittest.main()
