import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "scripts" / "ollama-web-chat.py"


def load_app_module(host: str = "127.0.0.1", extra_env: dict | None = None) -> types.ModuleType:
    env_keys = {
        "OLLAMA_WEB_HOST": host,
        "OLLAMA_WEB_PORT": "8088",
        "OLLAMA_WEB_API_KEY": "",
        "OLLAMA_WEB_UPDATE_BRANCH": "main",
    }
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-update-test-") as td:
        state_dir = Path(td)
        env_keys.update(
            {
                "OLLAMA_WEB_HISTORY_PATH": str(state_dir / "history.json"),
                "OLLAMA_WEB_STASH_PATH": str(state_dir / "stash.json"),
                "OLLAMA_WEB_PDF_INDEX_DB": str(state_dir / "pdf-rag.sqlite"),
                "OLLAMA_WEB_PDF_SOURCE": str(state_dir / "library"),
            }
        )
        if extra_env:
            env_keys.update(extra_env)

        previous = {k: os.environ.get(k) for k in env_keys}
        os.environ.update(env_keys)
        try:
            module_name = f"ollama_web_chat_update_test_{os.getpid()}_{id(state_dir)}"
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


class UpdateFlowTests(unittest.TestCase):
    def test_invalid_update_events_max_falls_back_to_default(self):
        app = load_app_module(extra_env={"OLLAMA_WEB_UPDATE_EVENTS_MAX": "not-an-int"})
        self.assertEqual(app.UPDATE_EVENTS_MAX, 200)

    def test_parse_semver(self):
        app = load_app_module()
        self.assertEqual(app._parse_semver("v1.2.3"), (1, 2, 3))
        self.assertEqual(app._parse_semver("1.2.3"), (1, 2, 3))
        self.assertIsNone(app._parse_semver("1.2"))
        self.assertIsNone(app._parse_semver("v1.2.x"))

    def test_is_newer_version(self):
        app = load_app_module()
        self.assertTrue(app.is_newer_version("v1.2.4", "v1.2.3"))
        self.assertFalse(app.is_newer_version("v1.2.3", "v1.2.3"))
        self.assertFalse(app.is_newer_version("invalid", "v1.2.3"))

    def test_start_update_apply_rejects_invalid_target(self):
        app = load_app_module()
        out = app.start_update_apply("bad target with spaces")
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("error_code"), "invalid_target")

    def test_start_update_apply_rejects_when_running(self):
        app = load_app_module()
        with app.UPDATE_LOCK:
            app.UPDATE_STATE["running"] = True
        out = app.start_update_apply("main")
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("error_code"), "already_running")

    def test_check_for_updates_sets_release_notes_url(self):
        app = load_app_module()
        app.read_current_version = lambda: "v1.0.0"
        app.fetch_latest_release = lambda: {
            "tag": "v1.1.0",
            "published_at": "2026-01-01T00:00:00Z",
            "notes_url": "https://example.com/release-notes",
        }
        out = app.check_for_updates()
        self.assertTrue(out["ok"])
        self.assertEqual(out.get("release_notes_url"), "https://example.com/release-notes")
        self.assertTrue(out.get("update_available"))

    def test_check_for_updates_rejects_unsafe_release_notes_url(self):
        app = load_app_module()
        app.read_current_version = lambda: "v1.0.0"
        app.fetch_latest_release = lambda: {
            "tag": "v1.1.0",
            "published_at": "2026-01-01T00:00:00Z",
            "notes_url": "javascript:alert(1)",
        }
        out = app.check_for_updates()
        self.assertTrue(out["ok"])
        self.assertIsNone(out.get("release_notes_url"))
        self.assertIsNone((out.get("release") or {}).get("notes_url"))

    def test_update_events_capture_recent_state(self):
        app = load_app_module()
        app._set_update_state(state="checking", step="fetch_latest_release", message="Checking latest")
        app._set_update_state(state="idle", step="checked", message="You are up to date")

        payload = app.get_update_events(limit=2)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 2)
        self.assertGreaterEqual(payload["total_count"], 2)
        self.assertEqual(payload["events"][0].get("state"), "idle")

    def test_update_events_limit_uses_configured_max(self):
        app = load_app_module(extra_env={"OLLAMA_WEB_UPDATE_EVENTS_MAX": "350"})
        for i in range(360):
            app._set_update_state(state="checking", step=f"step-{i}", message="Checking latest")

        payload = app.get_update_events(limit=1000)
        self.assertEqual(payload["count"], 350)
        self.assertEqual(len(payload["events"]), 350)


if __name__ == "__main__":
    unittest.main()
