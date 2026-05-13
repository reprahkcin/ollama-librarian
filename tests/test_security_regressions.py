import importlib.util
import os
import re
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "scripts" / "ollama-web-chat.py"


def load_app_module(host: str = "127.0.0.1", api_key: str = "") -> types.ModuleType:
    env_keys = {
        "OLLAMA_WEB_HOST": host,
        "OLLAMA_WEB_PORT": "8088",
        "OLLAMA_WEB_API_KEY": api_key,
    }
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-test-") as td:
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
            module_name = f"ollama_web_chat_test_{os.getpid()}_{id(state_dir)}"
            spec = importlib.util.spec_from_file_location(
                module_name, APP_PATH)
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


class SecurityRegressionTests(unittest.TestCase):
    def test_non_loopback_bind_is_always_rejected(self):
        app = load_app_module(host="0.0.0.0", api_key="test-key")

        with self.assertRaises(SystemExit) as cm:
            app.main()

        message = str(cm.exception)
        self.assertIn("Refusing non-loopback bind", message)

    def test_same_origin_guard_rejects_mismatched_origin(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.headers = {
            "Host": "127.0.0.1:8088",
            "Origin": "http://evil.test",
        }

        sent = {}

        def fake_send(code, body, content_type="application/json; charset=utf-8"):
            sent["code"] = code
            sent["body"] = body
            sent["content_type"] = content_type

        handler._send = fake_send

        allowed = app.Handler._require_same_origin_for_state_change(
            handler, "/api/history"
        )
        self.assertFalse(allowed)
        self.assertEqual(sent.get("code"), 403)
        self.assertIn("Origin not allowed", sent.get("body", ""))

    def test_same_origin_guard_allows_matching_origin(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.headers = {
            "Host": "127.0.0.1:8088",
            "Origin": "http://127.0.0.1:8088",
            "Referer": "http://127.0.0.1:8088/",
        }

        handler._send = lambda *args, **kwargs: None
        allowed = app.Handler._require_same_origin_for_state_change(
            handler, "/api/history"
        )
        self.assertTrue(allowed)

    def test_citation_rendering_escapes_html_before_innerhtml(self):
        source = APP_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            re.compile(
                r"text\.innerHTML\s*=\s*renderInlineMarkdown\(\s*escapeHtml\(\s*String\(entry\.citation\s*\|\|\s*''\)\s*\)\s*\)\s*;"
            ),
        )

    def test_csp_uses_nonce_for_scripts_on_main_page(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.path = "/"
        handler._csp_nonce = "nonce-test-value"

        captured = {}

        def fake_send_header(name, value):
            captured[name] = value

        handler.send_header = fake_send_header

        app.Handler._send_security_headers(handler)

        csp = captured.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self' 'nonce-nonce-test-value'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)

    def test_csp_uses_nonce_for_scripts_on_epub_reader(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.path = "/epub-reader"
        handler._csp_nonce = "nonce-test-value"

        captured = {}

        def fake_send_header(name, value):
            captured[name] = value

        handler.send_header = fake_send_header

        app.Handler._send_security_headers(handler)

        csp = captured.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self' 'nonce-nonce-test-value'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)


if __name__ == "__main__":
    unittest.main()
