import json
import importlib.util
import os
import sqlite3
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEXER_PATH = REPO_ROOT / "src" / "ollama_librarian" / "indexer.py"


def load_indexer_module() -> types.ModuleType:
    module_name = f"ollama_librarian_indexer_calibration_test_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, INDEXER_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to create import spec for indexer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.indexer = load_indexer_module()

    def test_semantic_drift_penalty_demotes_high_vector_irrelevant_chunk(self):
        conn = sqlite3.connect(":memory:")

        original_loader = self.indexer.load_all_chunks
        try:
            self.indexer.load_all_chunks = lambda _conn: [
                (
                    "high-vector-unrelated.pdf",
                    "Macroeconomic Overview",
                    1,
                    "An unrelated overview of manufacturing output and fiscal balances.",
                    json.dumps([1.0, 0.0]),
                ),
                (
                    "bonus-army-context.pdf",
                    "Context",
                    2,
                    "Bonus Army protests occurred in Washington and became significant.",
                    json.dumps([0.68, 0.0]),
                ),
            ]

            top = self.indexer.retrieve_top_chunks_filtered(
                conn,
                [1.0, 0.0],
                2,
                "Bonus Army political significance",
                None,
                None,
            )
        finally:
            self.indexer.load_all_chunks = original_loader
            conn.close()

        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][1], "bonus-army-context.pdf")

    def test_entity_alignment_boost_helps_title_only_entity_match(self):
        conn = sqlite3.connect(":memory:")

        original_loader = self.indexer.load_all_chunks
        try:
            self.indexer.load_all_chunks = lambda _conn: [
                (
                    "generic-finance.pdf",
                    "Economic Policy Notes",
                    4,
                    "The corporation provided emergency lending support to institutions.",
                    json.dumps([0.93, 0.0]),
                ),
                (
                    "rfc-primer.pdf",
                    "Reconstruction Finance Corporation Primer",
                    5,
                    "It was established to stabilize key credit channels.",
                    json.dumps([0.74, 0.0]),
                ),
            ]

            top = self.indexer.retrieve_top_chunks_filtered(
                conn,
                [1.0, 0.0],
                2,
                "What is the Reconstruction Finance Corporation and what was its purpose?",
                None,
                None,
            )
        finally:
            self.indexer.load_all_chunks = original_loader
            conn.close()

        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][1], "rfc-primer.pdf")


if __name__ == "__main__":
    unittest.main()
