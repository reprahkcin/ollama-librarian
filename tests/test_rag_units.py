import importlib.util
import os
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RAG_PATH = REPO_ROOT / "scripts" / "pdf_library_rag.py"


def load_rag_module() -> types.ModuleType:
    module_name = f"pdf_library_rag_test_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, RAG_PATH)
    if not spec or not spec.loader:
        raise RuntimeError(
            "Failed to create import spec for pdf_library_rag.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RagUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = load_rag_module()

    def test_clean_title_candidate_strips_noise(self):
        cleaned = self.rag.clean_title_candidate(
            "01 - Deep_Learning - PDF Drive")
        self.assertEqual(cleaned, "Deep Learning")

    def test_looks_like_author_name(self):
        self.assertTrue(self.rag.looks_like_author_name("Ada Lovelace"))
        self.assertFalse(self.rag.looks_like_author_name("Ada Lovelace 2024"))

    def test_infer_author_and_title_from_path(self):
        author, title = self.rag.infer_author_and_title_from_path(
            Path("Ian Goodfellow - Deep Learning.pdf")
        )
        self.assertEqual(author, "Ian Goodfellow")
        self.assertEqual(title, "Deep Learning")

        author, title = self.rag.infer_author_and_title_from_path(
            Path("Graph Models by Jane Doe.pdf")
        )
        self.assertEqual(author, "Jane Doe")
        self.assertEqual(title, "Graph Models")

    def test_split_authors_normalizes_and_dedupes(self):
        authors = self.rag.split_authors(
            "By Ada Lovelace; Alan Turing and Ada Lovelace & z-lib")
        self.assertEqual(authors, ["Ada Lovelace", "Alan Turing"])

    def test_extract_year_finds_first_valid_year(self):
        self.assertEqual(self.rag.extract_year(
            "updated 2024 revision"), "2024")
        self.assertEqual(self.rag.extract_year("no year here"), "")

    def test_strip_html_to_text_removes_tags(self):
        text = self.rag.strip_html_to_text(
            "<h1>Title</h1><p>Hello <b>world</b></p><div>Line 2</div>")
        self.assertIn("Title", text)
        self.assertIn("Hello world", text)
        self.assertIn("Line 2", text)
        self.assertNotIn("<h1>", text)

    def test_cosine_similarity(self):
        score = self.rag.cosine_similarity([1.0, 0.0], [1.0, 0.0])
        self.assertAlmostEqual(score, 1.0, places=6)

        self.assertEqual(self.rag.cosine_similarity([], []), -1.0)
        self.assertEqual(self.rag.cosine_similarity([1.0], [1.0, 2.0]), -1.0)
        self.assertEqual(self.rag.cosine_similarity(
            [0.0, 0.0], [0.0, 0.0]), -1.0)

    def test_chunk_text(self):
        text = "abcdefghij"
        chunks = self.rag.chunk_text(text, chunk_size=4, overlap=1)
        self.assertEqual(chunks, ["abcd", "defg", "ghij"])

        small = self.rag.chunk_text(" a   b ", chunk_size=20, overlap=0)
        self.assertEqual(small, ["a b"])
        self.assertEqual(self.rag.chunk_text("", chunk_size=5, overlap=1), [])


if __name__ == "__main__":
    unittest.main()
