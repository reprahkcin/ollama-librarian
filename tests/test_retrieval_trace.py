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
        self.assertIn("final_score", first)

        expected_final = (
            first["vector_score"]
            + first["lexical_path_title_score"]
            + first["lexical_chunk_score"]
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


if __name__ == "__main__":
    unittest.main()
