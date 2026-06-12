import importlib.util
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from tests.helpers.server_harness import running_server


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
                raise RuntimeError(
                    "Failed to create import spec for ollama-web-chat.py")
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
        app = load_app_module()
        app_js_path = Path(app.ASSET_ROOT) / "app.js"
        source = app_js_path.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            re.compile(
                r"text\.innerHTML\s*=\s*renderInlineMarkdown\(\s*escapeHtml\(\s*String\(entry\.citation\s*\|\|\s*(?:''|\"\")\)\s*\)\s*,?\s*\)\s*;",
                re.DOTALL,
            ),
        )

    def test_csp_uses_self_only_scripts_on_main_page(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.path = "/"

        captured = {}

        def fake_send_header(name, value):
            captured[name] = value

        handler.send_header = fake_send_header

        app.Handler._send_security_headers(handler)

        csp = captured.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("nonce-", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)

    def test_csp_uses_self_only_scripts_on_epub_reader(self):
        app = load_app_module()
        handler = object.__new__(app.Handler)
        handler.path = "/epub-reader"

        captured = {}

        def fake_send_header(name, value):
            captured[name] = value

        handler.send_header = fake_send_header

        app.Handler._send_security_headers(handler)

        csp = captured.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("nonce-", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)

    def test_abstract_recommendation_normalization(self):
        app = load_app_module()
        self.assertEqual(
            app._normalize_recommendation("download and index", 10),
            "download_and_index",
        )
        self.assertEqual(app._normalize_recommendation("skip", 90), "skip")
        self.assertEqual(app._normalize_recommendation(
            "", 76), "download_and_index")
        self.assertEqual(app._normalize_recommendation("", 52), "maybe")
        self.assertEqual(app._normalize_recommendation("", 20), "skip")

    def test_abstract_json_extraction_fallback(self):
        app = load_app_module()
        parsed = app._extract_json_object(
            'result:\n{"confidence": 88, "recommendation": "maybe"}\nthanks'
        )
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("confidence"), 88)
        self.assertEqual(parsed.get("recommendation"), "maybe")

    def test_safe_mode_clamps_client_num_thread_to_policy_max(self):
        with running_server() as (app, base_url):
            original_proxy = app.Handler._proxy
            original_policy = app.get_current_safety_policy
            original_validate = app.validate_model_allowed
            captured = {}

            def fake_proxy(handler, method, path, data):
                captured["payload"] = json.loads(data.decode("utf-8"))
                return handler._send(
                    200,
                    json.dumps({"response": "ok"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            app.get_current_safety_policy = lambda: {
                "pressure": "throttled",
                "allow_new_work": True,
                "max_generation_slots": 1,
                "embed_num_thread": 1,
            }
            app.validate_model_allowed = lambda model: {"ok": True}
            app.Handler._proxy = fake_proxy
            try:
                req = Request(
                    f"{base_url}/api/generate",
                    data=json.dumps(
                        {
                            "model": "llama3.1:8b",
                            "prompt": "hello",
                            "stream": False,
                            # Malicious client tries to bypass throttling
                            "options": {"num_thread": 64},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=10) as resp:
                    status = resp.status
            finally:
                app.Handler._proxy = original_proxy
                app.get_current_safety_policy = original_policy
                app.validate_model_allowed = original_validate

        self.assertEqual(status, 200)
        # The client-supplied num_thread must be clamped down to the policy
        # maximum, not honored as-is.
        self.assertEqual(
            captured.get("payload", {}).get("options", {}).get("num_thread"), 1
        )


if __name__ == "__main__":
    unittest.main()
