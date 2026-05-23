import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "scripts" / "ollama-web-chat.py"
RAG_PATH = REPO_ROOT / "scripts" / "pdf_library_rag.py"


def load_web_module() -> types.ModuleType:
    env_keys = {
        "OLLAMA_WEB_HOST": "127.0.0.1",
        "OLLAMA_WEB_PORT": "8088",
        "OLLAMA_WEB_API_KEY": "",
    }
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-path-web-") as td:
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
            module_name = f"ollama_web_chat_path_test_{os.getpid()}_{id(state_dir)}"
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


def load_rag_module() -> types.ModuleType:
    module_name = f"pdf_library_rag_path_test_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, RAG_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to create import spec for pdf_library_rag.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PathDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = load_web_module()
        cls.rag = load_rag_module()

    def test_web_defaults_do_not_reference_home_network_setup(self):
        self.assertNotIn("home-network-setup", self.web.HISTORY_PATH)
        self.assertNotIn("home-network-setup", self.web.PDF_INDEX_DB)
        self.assertNotIn("home-network-setup", self.web.resolve_default_stash_path())

    def test_rag_index_db_default_uses_ollama_librarian_state_dir(self):
        parser = self.rag.build_parser()
        args = parser.parse_args(["status"])
        self.assertIn("ollama-librarian", args.index_db)
        self.assertNotIn("home-network-setup", args.index_db)

    def test_state_dir_resolves_per_platform(self):
        with patch("platform.system", return_value="Darwin"):
            mac_path = str(self.web.resolve_default_state_dir())
            self.assertTrue(mac_path.endswith("Library/Application Support/ollama-librarian"))

        with patch("platform.system", return_value="Linux"), patch.dict(
            os.environ, {"XDG_DATA_HOME": "/tmp/xdg-home"}, clear=False
        ):
            linux_path = str(self.web.resolve_default_state_dir())
            self.assertEqual(linux_path, "/tmp/xdg-home/ollama-librarian")

        with patch("platform.system", return_value="Windows"), patch.dict(
            os.environ, {"APPDATA": "C:/Users/test/AppData/Roaming"}, clear=False
        ):
            windows_path = str(self.web.resolve_default_state_dir())
            self.assertEqual(windows_path, "C:/Users/test/AppData/Roaming/ollama-librarian")

    def test_pdf_source_fallback_prefers_documents_path(self):
        with patch("os.path.exists", return_value=False):
            web_default = self.web.resolve_default_pdf_source()
            rag_default = self.rag.resolve_default_pdf_source()

        self.assertTrue(web_default.endswith("Documents/LLM Library"))
        self.assertTrue(rag_default.endswith("Documents/LLM Library"))


if __name__ == "__main__":
    unittest.main()
