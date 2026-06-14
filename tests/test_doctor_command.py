import importlib.util
import io
import os
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
RAG_PATH = REPO_ROOT / "scripts" / "pdf_library_rag.py"


def load_rag_module() -> types.ModuleType:
    module_name = f"pdf_library_rag_doctor_test_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, RAG_PATH)
    if not spec or not spec.loader:
        raise RuntimeError(
            "Failed to create import spec for pdf_library_rag.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = load_rag_module()

    def test_parser_includes_doctor_subcommand(self):
        parser = self.rag.build_parser()
        args = parser.parse_args(["doctor", "--json-output"])
        self.assertEqual(args.cmd, "doctor")

    def test_model_available_allows_base_name_match(self):
        self.assertTrue(
            self.rag._model_available("qwen2.5:14b", ["qwen2.5:latest"])
        )
        self.assertFalse(self.rag._model_available(
            "mistral:7b", ["qwen2.5:latest"]))

    def test_doctor_model_recommendation_reports_safe_choice(self):
        original_detect = self.rag.detect_hardware_profile
        original_recommend = self.rag.recommend_model

        self.rag.detect_hardware_profile = lambda: object()
        self.rag.recommend_model = lambda models, hardware: {
            "recommended_model": "llama3.1:8b",
            "reason": "best_safe_installed_model",
            "safe_budget_gb": 8.8,
            "models": [
                {"name": "llama3.1:8b", "safety": "safe"},
                {"name": "qwen2.5:14b", "safety": "unsafe"},
            ],
        }
        try:
            result = self.rag._doctor_check_model_recommendation(
                ["llama3.1:8b", "qwen2.5:14b"])
        finally:
            self.rag.detect_hardware_profile = original_detect
            self.rag.recommend_model = original_recommend

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("check"), "model_fit_recommendation")
        self.assertIn("llama3.1:8b", result.get("message", ""))
        self.assertIn("unsafe=qwen2.5:14b", result.get("message", ""))

    def test_doctor_command_returns_success_when_all_checks_pass(self):
        with tempfile.TemporaryDirectory(prefix="doctor-test-") as td:
            tmp = Path(td)
            source_dir = tmp / "library"
            source_dir.mkdir(parents=True, exist_ok=True)
            index_db = tmp / "state" / "pdf-rag.sqlite"
            index_db.parent.mkdir(parents=True, exist_ok=True)

            args = SimpleNamespace(
                ollama_base="http://127.0.0.1:11434",
                embed_model="nomic-embed-text",
                answer_model="qwen2.5:14b",
                required_model=[],
                index_db=str(index_db),
                source=str(source_dir),
                web_host="127.0.0.1",
                web_port=65534,
                timeout=1,
                json_output=True,
            )

            original_fetch = self.rag._fetch_ollama_model_names
            original_port = self.rag._doctor_check_port_available
            original_deps = self.rag._doctor_check_dependency_imports
            self.rag._fetch_ollama_model_names = lambda *_args, **_kwargs: [
                "nomic-embed-text",
                "qwen2.5:14b",
            ]
            self.rag._doctor_check_port_available = (
                lambda host, port: self.rag._doctor_result(
                    "web_port_available", True, f"Port {port} on {host} is available"
                )
            )
            self.rag._doctor_check_dependency_imports = lambda: [
                self.rag._doctor_result(
                    "import_pypdf", True, "pypdf import ok"),
                self.rag._doctor_result(
                    "import_ebooklib", True, "ebooklib import ok"),
            ]
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = self.rag.doctor_command(args)
                output = buf.getvalue()
                self.assertEqual(code, 0)
                self.assertIn('"ok": true', output.lower())
            finally:
                self.rag._fetch_ollama_model_names = original_fetch
                self.rag._doctor_check_port_available = original_port
                self.rag._doctor_check_dependency_imports = original_deps

    def test_doctor_command_returns_failure_when_checks_fail(self):
        args = SimpleNamespace(
            ollama_base="http://127.0.0.1:11434",
            embed_model="nomic-embed-text",
            answer_model="qwen2.5:14b",
            required_model=[],
            index_db="/path/does/not/exist/db.sqlite",
            source="/path/does/not/exist/library",
            web_host="127.0.0.1",
            web_port=8088,
            timeout=1,
            json_output=False,
        )

        original_python = self.rag._doctor_check_python_version
        self.rag._doctor_check_python_version = (
            lambda *a, **k: self.rag._doctor_result(
                "python_version", False, "Python too old"
            )
        )
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = self.rag.doctor_command(args)
            output = buf.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("FAIL", output)
        finally:
            self.rag._doctor_check_python_version = original_python


if __name__ == "__main__":
    unittest.main()
