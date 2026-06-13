import json
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tests.helpers.server_harness import running_server


def _request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict | list | str, dict]:
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = body
            return resp.status, parsed, dict(resp.headers)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = body
        try:
            return exc.code, parsed, dict(exc.headers)
        finally:
            exc.close()


class RouteBaselineTests(unittest.TestCase):
    def test_get_tags_proxies_via_handler(self):
        with running_server() as (app, base_url):
            original_proxy = app.Handler._proxy

            def fake_proxy(handler, method, path, data):
                self.assertEqual(method, "GET")
                self.assertEqual(path, "/api/tags")
                return handler._send(
                    200,
                    json.dumps(
                        {"models": [{"name": "stub-model"}]}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            app.Handler._proxy = fake_proxy
            try:
                status, payload, _ = _request_json(
                    "GET", f"{base_url}/api/tags")
            finally:
                app.Handler._proxy = original_proxy

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("models", [])[
                         0].get("name"), "stub-model")

    def test_get_history_returns_messages_payload(self):
        with running_server() as (_, base_url):
            status, payload, headers = _request_json(
                "GET", f"{base_url}/api/history")

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertIn("messages", payload)
        self.assertIsInstance(payload.get("messages"), list)
        self.assertIn("application/json", headers.get("Content-Type", ""))

    def test_post_history_appends_entry(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/history",
                {"role": "user", "text": "phase-0 check",
                    "ts": "2026-05-22T00:00:00Z"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True})

            status, history, _ = _request_json(
                "GET", f"{base_url}/api/history")

        self.assertEqual(status, 200)
        self.assertIsInstance(history, dict)
        self.assertIsInstance(history.get("messages"), list)
        self.assertEqual(len(history["messages"]), 1)
        self.assertEqual(history["messages"][0].get("role"), "user")
        self.assertEqual(history["messages"][0].get("text"), "phase-0 check")

    def test_delete_history_clears_messages(self):
        with running_server() as (_, base_url):
            status, _, _ = _request_json(
                "POST",
                f"{base_url}/api/history",
                {"role": "user", "text": "to-clear"},
            )
            self.assertEqual(status, 200)

            status, payload, _ = _request_json(
                "DELETE", f"{base_url}/api/history")
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True})

            status, history, _ = _request_json(
                "GET", f"{base_url}/api/history")

        self.assertEqual(status, 200)
        self.assertEqual(history.get("messages"), [])

    def test_get_and_post_instructions_round_trip(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/instructions")
            self.assertEqual(status, 200)
            self.assertIsInstance(payload, dict)
            self.assertIn("instructions", payload)

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/instructions",
                {"instructions": "Use concise academic style."},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True})

            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/instructions")

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("instructions"),
                         "Use concise academic style.")

    def test_get_library_docs_returns_expected_shape(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/library/docs")

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("ok"))
        self.assertIn("documents", payload)
        self.assertIn("count", payload)

    def test_stash_get_post_delete_flow(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/stash?limit=200")
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))
            self.assertIsInstance(payload.get("entries"), list)

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/stash",
                {"text": "Saved answer", "entry_type": "response"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))

            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/stash?limit=200")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(payload.get("count", 0), 1)
            stash_id = payload["entries"][0].get("stash_id")
            self.assertIsInstance(stash_id, int)

            status, payload, _ = _request_json(
                "DELETE", f"{base_url}/api/stash?id={stash_id}")

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))

    def test_bibliography_routes_filter_and_clear(self):
        with running_server() as (_, base_url):
            status, _, _ = _request_json(
                "POST",
                f"{base_url}/api/stash",
                {"text": "Bib item", "entry_type": "bibliography"},
            )
            self.assertEqual(status, 200)
            status, _, _ = _request_json(
                "POST",
                f"{base_url}/api/stash",
                {"text": "Regular item", "entry_type": "response"},
            )
            self.assertEqual(status, 200)

            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/bibliography?limit=200")
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("entry_type"), "bibliography")
            self.assertEqual(payload.get("count"), 1)

            status, payload, _ = _request_json(
                "DELETE", f"{base_url}/api/bibliography?all=1")
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))

            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/bibliography?limit=200")

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("count"), 0)

    def test_get_pdf_status_returns_shape(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/pdf/status")

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertIn("ok", payload)
        self.assertIn("source_path", payload)

    def test_post_pdf_index_pause_is_stable_when_not_running(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "POST", f"{base_url}/api/pdf/index/pause", {}
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("paused"))
        self.assertIn("message", payload)

    def test_post_pdf_source_updates_runtime_source_path(self):
        with running_server() as (app, base_url):
            target = Path(app.DEFAULT_STATE_DIR) / "custom-library"
            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/pdf/source",
                {"source_path": str(target)},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))

            status, status_payload, _ = _request_json(
                "GET", f"{base_url}/api/pdf/status")

        self.assertEqual(status, 200)
        self.assertTrue(Path(target).is_dir())
        self.assertEqual(
            str(Path(target).resolve()),
            str(status_payload.get("source_path", "")),
        )

    def test_post_pdf_source_rejects_empty_path(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/pdf/source",
                {"source_path": "   "},
            )

        self.assertEqual(status, 400)
        self.assertFalse(payload.get("ok", True))
        self.assertIn("source_path", str(payload.get("error", "")))

    def test_post_pdf_source_pick_sets_selected_directory(self):
        with running_server() as (app, base_url):
            target = Path(app.DEFAULT_STATE_DIR) / "picked-library"
            original_picker = app._pick_directory_with_native_dialog
            app._pick_directory_with_native_dialog = lambda: str(target)
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/source/pick",
                    {},
                )
            finally:
                app._pick_directory_with_native_dialog = original_picker

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("canceled", True))
        self.assertEqual(str(target.resolve()), payload.get("source_path"))

    def test_post_pdf_source_pick_handles_cancel(self):
        with running_server() as (app, base_url):
            original_picker = app._pick_directory_with_native_dialog
            app._pick_directory_with_native_dialog = lambda: None
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/source/pick",
                    {},
                )
            finally:
                app._pick_directory_with_native_dialog = original_picker

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("canceled"))

    def test_post_pdf_source_pick_handles_runtime_error_as_recoverable(self):
        with running_server() as (app, base_url):
            original_picker = app._pick_directory_with_native_dialog

            def _raise_runtime_error():
                raise RuntimeError("picker timed out")

            app._pick_directory_with_native_dialog = _raise_runtime_error
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/source/pick",
                    {},
                )
            finally:
                app._pick_directory_with_native_dialog = original_picker

        self.assertEqual(status, 200)
        self.assertFalse(payload.get("ok", True))
        self.assertTrue(payload.get("recoverable"))
        self.assertIn("timed out", str(payload.get("error", "")))

    def test_get_pdf_file_serves_inline_content(self):
        with running_server() as (app, base_url):
            pdf_dir = Path(app.PDF_SOURCE)
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / "inline-test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            encoded_path = quote(str(pdf_path), safe="")

            req = Request(
                f"{base_url}/api/pdf/file?path={encoded_path}", method="GET")
            with urlopen(req, timeout=10) as resp:
                headers = dict(resp.headers)
                self.assertEqual(resp.status, 200)
                self.assertIn("application/pdf",
                              headers.get("Content-Type", ""))
                self.assertIn(
                    "inline;",
                    headers.get("Content-Disposition", ""),
                )

    def test_pdf_reader_route_resolves_to_pdf_response(self):
        with running_server() as (app, base_url):
            pdf_dir = Path(app.PDF_SOURCE)
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / "redirect-test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            encoded_path = quote(str(pdf_path), safe="")

            req = Request(
                f"{base_url}/pdf-reader?path={encoded_path}&page=7",
                method="GET",
            )
            with urlopen(req, timeout=10) as resp:
                final_url = resp.geturl()
                headers = dict(resp.headers)
                self.assertEqual(resp.status, 200)
                self.assertIn("/api/pdf/file?path=", final_url)
                self.assertIn("application/pdf",
                              headers.get("Content-Type", ""))

    def test_get_update_status_returns_shape(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/update/status")

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertIn("running", payload)
        self.assertIn("state", payload)

    def test_get_system_profile_returns_recommendation_shape(self):
        with running_server() as (app, base_url):
            original_build = app.build_system_profile
            original_fetch = app.fetch_ollama_model_items

            def fake_build(models):
                return {
                    "ok": True,
                    "hardware": {"total_memory_gb": 16},
                    "resource_state": {"pressure": "ok"},
                    "recommendation": {
                        "recommended_model": "llama3.1:8b",
                        "models": [
                            {"name": "llama3.1:8b", "safety": "safe"},
                        ],
                    },
                }

            app.fetch_ollama_model_items = lambda timeout=10, force_refresh=False: [
                {"name": "llama3.1:8b"},
            ]
            app.build_system_profile = fake_build
            try:
                status, payload, _ = _request_json(
                    "GET", f"{base_url}/api/system/profile")
            finally:
                app.build_system_profile = original_build
                app.fetch_ollama_model_items = original_fetch

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(
            payload.get("recommendation", {}).get("recommended_model"),
            "llama3.1:8b",
        )
        self.assertTrue(payload.get("ollama", {}).get("reachable"))

    def test_get_system_profile_refresh_query_forces_model_refresh(self):
        with running_server() as (app, base_url):
            original_build = app.build_system_profile
            original_fetch = app.fetch_ollama_model_items
            calls = []

            app.build_system_profile = lambda models: {
                "ok": True,
                "hardware": {},
                "resource_state": {"pressure": "ok"},
                "recommendation": {"recommended_model": "llama3.1:8b", "models": []},
            }

            def fake_fetch(timeout=10, force_refresh=False):
                calls.append(bool(force_refresh))
                return [{"name": "llama3.1:8b"}]

            app.fetch_ollama_model_items = fake_fetch
            try:
                status, payload, _ = _request_json(
                    "GET", f"{base_url}/api/system/profile?refresh=1")
            finally:
                app.build_system_profile = original_build
                app.fetch_ollama_model_items = original_fetch

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(calls, [True])

    def test_fetch_ollama_model_items_merges_show_metadata(self):
        with running_server() as (app, _base_url):
            original_urlopen = app.urlopen
            original_base = app.OLLAMA_BASE
            original_ttl = app.MODEL_CACHE_TTL_SECONDS

            class FakeResponse:
                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self):
                    return json.dumps(self.payload).encode("utf-8")

            def fake_urlopen(req, timeout=10):
                url = str(req.full_url)
                if url.endswith("/api/tags"):
                    return FakeResponse({
                        "models": [{"name": "llama3.1:8b", "size": 5}]
                    })
                if url.endswith("/api/show"):
                    return FakeResponse({
                        "details": {
                            "parameter_size": "8.0B",
                            "quantization_level": "Q4_K_M",
                            "family": "llama",
                        },
                        "model_info": {"llama.context_length": 8192},
                    })
                raise AssertionError(url)

            app.urlopen = fake_urlopen
            app.OLLAMA_BASE = "http://ollama.test"
            app.MODEL_CACHE_TTL_SECONDS = 0
            try:
                models = app.fetch_ollama_model_items(timeout=3)
            finally:
                app.clear_model_cache()
                app.urlopen = original_urlopen
                app.OLLAMA_BASE = original_base
                app.MODEL_CACHE_TTL_SECONDS = original_ttl

        self.assertEqual(models[0].get(
            "details", {}).get("parameter_size"), "8.0B")
        self.assertEqual(models[0].get("model_info", {}).get(
            "llama.context_length"), 8192)

    def test_fetch_ollama_model_items_uses_cache_until_forced(self):
        with running_server() as (app, _base_url):
            original_urlopen = app.urlopen
            original_base = app.OLLAMA_BASE
            original_ttl = app.MODEL_CACHE_TTL_SECONDS
            calls = {"tags": 0, "show": 0}

            class FakeResponse:
                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self):
                    return json.dumps(self.payload).encode("utf-8")

            def fake_urlopen(req, timeout=10):
                url = str(req.full_url)
                if url.endswith("/api/tags"):
                    calls["tags"] += 1
                    return FakeResponse({
                        "models": [{"name": "llama3.1:8b", "size": 5}]
                    })
                if url.endswith("/api/show"):
                    calls["show"] += 1
                    return FakeResponse({
                        "details": {
                            "parameter_size": "8.0B",
                            "quantization_level": "Q4_K_M",
                        },
                    })
                raise AssertionError(url)

            app.urlopen = fake_urlopen
            app.OLLAMA_BASE = "http://ollama-cache.test"
            app.MODEL_CACHE_TTL_SECONDS = 60
            app.clear_model_cache()
            try:
                first = app.fetch_ollama_model_items(timeout=3)
                second = app.fetch_ollama_model_items(timeout=3)
                refreshed = app.fetch_ollama_model_items(
                    timeout=3, force_refresh=True)
            finally:
                app.clear_model_cache()
                app.urlopen = original_urlopen
                app.OLLAMA_BASE = original_base
                app.MODEL_CACHE_TTL_SECONDS = original_ttl

        self.assertEqual(first, second)
        self.assertEqual(refreshed[0].get(
            "details", {}).get("parameter_size"), "8.0B")
        self.assertEqual(calls, {"tags": 2, "show": 2})

    def test_fetch_ollama_model_items_persists_and_reloads_cache(self):
        with running_server() as (app, _base_url):
            original_urlopen = app.urlopen
            original_base = app.OLLAMA_BASE
            original_ttl = app.MODEL_CACHE_TTL_SECONDS
            calls = {"tags": 0, "show": 0}

            class FakeResponse:
                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self):
                    return json.dumps(self.payload).encode("utf-8")

            def fake_urlopen(req, timeout=10):
                url = str(req.full_url)
                if url.endswith("/api/tags"):
                    calls["tags"] += 1
                    return FakeResponse({
                        "models": [{"name": "llama3.1:8b", "size": 5}]
                    })
                if url.endswith("/api/show"):
                    calls["show"] += 1
                    return FakeResponse({
                        "details": {"parameter_size": "8.0B"},
                    })
                raise AssertionError(url)

            app.urlopen = fake_urlopen
            app.OLLAMA_BASE = "http://ollama-persist.test"
            app.MODEL_CACHE_TTL_SECONDS = 60
            app.clear_model_cache()
            try:
                first = app.fetch_ollama_model_items(timeout=3)
                cache_file_exists = app.MODEL_CACHE_PATH.is_file()
                with app.MODEL_CACHE_LOCK:
                    app.MODEL_CACHE["models"] = []
                    app.MODEL_CACHE["cached_at"] = 0.0
                    app.MODEL_CACHE["base_url"] = ""
                    app.MODEL_CACHE["loaded_from_disk"] = False
                second = app.fetch_ollama_model_items(timeout=3)
                cache_state = app.get_model_cache_state()
            finally:
                app.clear_model_cache()
                app.urlopen = original_urlopen
                app.OLLAMA_BASE = original_base
                app.MODEL_CACHE_TTL_SECONDS = original_ttl

        self.assertTrue(cache_file_exists)
        self.assertEqual(first, second)
        self.assertEqual(calls, {"tags": 1, "show": 1})
        self.assertTrue(cache_state.get("loaded_from_disk"))

    def test_build_pdf_rag_command_passes_safe_answer_options(self):
        with running_server() as (app, _base_url):
            original_policy = app.get_current_safety_policy
            app.get_current_safety_policy = lambda force_detect=False: {
                "pressure": "throttled",
                "embed_num_thread": 1,
                "embed_delay_ms": 1500,
                "doc_cooldown_seconds": 45,
                "dynamic_max_threads": 1,
            }
            try:
                cmd, _env = app._build_pdf_rag_command(["status"])
            finally:
                app.get_current_safety_policy = original_policy

        self.assertIn("--answer-num-thread", cmd)
        self.assertEqual(cmd[cmd.index("--answer-num-thread") + 1], "1")
        self.assertIn("--answer-keep-alive", cmd)
        self.assertEqual(cmd[cmd.index("--answer-keep-alive") + 1], "15s")

    def test_post_generate_applies_safe_options_under_pressure(self):
        with running_server() as (app, base_url):
            original_proxy = app.Handler._proxy
            original_policy = app.get_current_safety_policy
            original_validate = app.validate_model_allowed
            captured = {}

            def fake_proxy(handler, method, path, data):
                captured["method"] = method
                captured["path"] = path
                captured["payload"] = json.loads(data.decode("utf-8"))
                return handler._send(
                    200,
                    json.dumps({"response": "ok"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            app.get_current_safety_policy = lambda force_detect=False: {
                "pressure": "throttled",
                "allow_new_work": True,
                "max_generation_slots": 1,
                "embed_num_thread": 1,
            }
            app.validate_model_allowed = lambda model: {"ok": True}
            app.Handler._proxy = fake_proxy
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {
                        "model": "llama3.1:8b",
                        "prompt": "hello",
                        "stream": False,
                        "keep_alive": "60s",
                    },
                )
            finally:
                app.Handler._proxy = original_proxy
                app.get_current_safety_policy = original_policy
                app.validate_model_allowed = original_validate

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("response"), "ok")
        self.assertEqual(captured.get("path"), "/api/generate")
        self.assertEqual(captured.get("payload", {}).get("keep_alive"), "15s")
        self.assertEqual(captured.get("payload", {}).get(
            "options", {}).get("num_thread"), 1)

    def test_get_system_health_includes_runtime_guard_state(self):
        with running_server() as (app, base_url):
            original_policy = app.get_current_safety_policy
            original_profile = app.get_system_profile

            def unexpected_profile_call(*_args, **_kwargs):
                raise AssertionError(
                    "health should not call full system profile")

            app.get_current_safety_policy = lambda force_detect=False: {
                "pressure": "ok",
                "allow_new_work": True,
                "max_generation_slots": 1,
            }
            app.get_system_profile = unexpected_profile_call
            try:
                status, payload, _ = _request_json(
                    "GET", f"{base_url}/api/system/health")
            finally:
                app.get_current_safety_policy = original_policy
                app.get_system_profile = original_profile

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("runtime", {}).get("safe_mode"))
        self.assertEqual(payload.get(
            "resource_state", {}).get("pressure"), "ok")
        self.assertTrue(payload.get("ollama", {}).get("not_checked"))

    def test_forced_pressure_override_controls_policy(self):
        with running_server() as (app, _base_url):
            original_force = app.FORCE_PRESSURE
            app.FORCE_PRESSURE = "throttled"
            try:
                policy = app.get_current_safety_policy()
                runtime = app.get_resource_runtime_state(policy)
            finally:
                app.FORCE_PRESSURE = original_force

        self.assertEqual(policy.get("pressure"), "throttled")
        self.assertTrue(policy.get("forced"))
        self.assertEqual(runtime.get("forced_pressure"), "throttled")

    def test_system_profile_uses_active_forced_pressure_policy(self):
        with running_server() as (app, base_url):
            original_force = app.FORCE_PRESSURE
            original_fetch = app.fetch_ollama_model_items
            app.FORCE_PRESSURE = "throttled"
            app.fetch_ollama_model_items = lambda timeout=10, force_refresh=False: []
            try:
                status, payload, _ = _request_json(
                    "GET", f"{base_url}/api/system/profile")
            finally:
                app.FORCE_PRESSURE = original_force
                app.fetch_ollama_model_items = original_fetch

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("resource_state", {}
                                     ).get("pressure"), "throttled")
        self.assertTrue(payload.get("resource_state", {}
                                    ).get("policy", {}).get("forced"))
        self.assertEqual(payload.get("runtime", {}).get(
            "forced_pressure"), "throttled")

    def test_post_pdf_index_blocked_when_resource_guard_rejects_start(self):
        with running_server() as (app, base_url):
            original_admit = app.admit_index_start
            app.admit_index_start = lambda: {
                "ok": False,
                "code": 503,
                "error": "System pressure is critical",
                "policy": {"pressure": "critical"},
            }
            try:
                status, payload, _ = _request_json(
                    "POST", f"{base_url}/api/pdf/index", {})
            finally:
                app.admit_index_start = original_admit

        self.assertEqual(status, 503)
        self.assertFalse(payload.get("ok", True))
        self.assertFalse(payload.get("started", True))
        self.assertIn("critical", str(payload.get("error", "")))

    def test_resource_monitor_tick_pauses_running_index_after_sustained_critical_pressure(self):
        with running_server() as (app, _base_url):
            original_policy = app.get_current_safety_policy
            original_pause = app.pause_pdf_index_job
            original_required = app.RESOURCE_MONITOR_CRITICAL_SAMPLES
            pause_calls = []

            app.RESOURCE_MONITOR_CRITICAL_SAMPLES = 2
            app.get_current_safety_policy = lambda force_detect=False: {
                "pressure": "critical",
                "pause_index": True,
                "message": "System pressure is critical.",
            }

            def fake_pause():
                pause_calls.append(True)
                with app.PDF_LOCK:
                    app.PDF_INDEX_STATE["pause_requested"] = True
                return {"ok": True, "paused": True, "message": "Pause requested"}

            app.pause_pdf_index_job = fake_pause
            with app.PDF_LOCK:
                app.PDF_INDEX_STATE["running"] = True
                app.PDF_INDEX_STATE["pause_requested"] = False
            with app.RESOURCE_LOCK:
                app.RESOURCE_STATE["monitor_critical_samples"] = 0
            try:
                first = app.resource_monitor_tick()
                second = app.resource_monitor_tick()
            finally:
                with app.PDF_LOCK:
                    app.PDF_INDEX_STATE["running"] = False
                    app.PDF_INDEX_STATE["pause_requested"] = False
                with app.RESOURCE_LOCK:
                    app.RESOURCE_STATE["monitor_critical_samples"] = 0
                app.get_current_safety_policy = original_policy
                app.pause_pdf_index_job = original_pause
                app.RESOURCE_MONITOR_CRITICAL_SAMPLES = original_required

        self.assertEqual(first.get("action"), "sampled")
        self.assertEqual(second.get("action"), "paused_index")
        self.assertEqual(len(pause_calls), 1)

    def test_resource_monitor_tick_resets_critical_sample_count_when_pressure_recovers(self):
        with running_server() as (app, _base_url):
            original_policy = app.get_current_safety_policy
            pressures = iter([
                {"pressure": "critical", "pause_index": True},
                {"pressure": "ok", "pause_index": False},
            ])
            app.get_current_safety_policy = lambda force_detect=False: next(pressures)
            with app.RESOURCE_LOCK:
                app.RESOURCE_STATE["monitor_critical_samples"] = 0
            try:
                app.resource_monitor_tick()
                app.resource_monitor_tick()
                with app.RESOURCE_LOCK:
                    critical_samples = app.RESOURCE_STATE["monitor_critical_samples"]
            finally:
                with app.RESOURCE_LOCK:
                    app.RESOURCE_STATE["monitor_critical_samples"] = 0
                app.get_current_safety_policy = original_policy

        self.assertEqual(critical_samples, 0)

    def test_post_pdf_ask_blocked_when_generation_slot_busy(self):
        with running_server() as (app, base_url):
            original_validate = app.validate_model_allowed
            original_policy = app.get_current_safety_policy
            app.validate_model_allowed = lambda model: {"ok": True}
            app.get_current_safety_policy = lambda force_detect=False: {
                "pressure": "ok",
                "allow_new_work": True,
                "max_generation_slots": 1,
                "message": "System pressure is normal.",
            }
            with app.RESOURCE_LOCK:
                app.RESOURCE_STATE["active_generations"] = 1
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "slot check",
                        "model": "llama3.1:8b",
                    },
                )
            finally:
                with app.RESOURCE_LOCK:
                    app.RESOURCE_STATE["active_generations"] = 0
                app.validate_model_allowed = original_validate
                app.get_current_safety_policy = original_policy

        self.assertEqual(status, 429)
        self.assertFalse(payload.get("ok", True))
        self.assertIn("already running", str(payload.get("error", "")))

    def test_post_pdf_ask_uses_recommended_model_when_omitted(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library
            original_recommended = app.get_recommended_model

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                self.assertEqual(model, "llama3.1:8b")
                return {
                    "ok": True,
                    "answer": "grounded answer",
                    "sources": [],
                }

            app.ask_pdf_library = fake_ask
            app.get_recommended_model = lambda default="qwen2.5:14b": "llama3.1:8b"
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "Who was Herbert Hoover?",
                        "top_k": 6,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask
                app.get_recommended_model = original_recommended

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))

    def test_post_abstract_evaluate_uses_normalized_contract(self):
        with running_server() as (app, base_url):
            original_eval = app.evaluate_abstract_relevance

            def fake_eval(model, research_need, abstract_text, instructions):
                self.assertEqual(model, "qwen2.5:14b")
                self.assertIn("need", research_need)
                self.assertIn("abstract", abstract_text)
                self.assertEqual(instructions, "")
                return {
                    "ok": True,
                    "recommendation": "download_and_index",
                    "confidence": 88,
                    "confidence_label": "high",
                    "reasons": ["Strong method fit"],
                }

            app.evaluate_abstract_relevance = fake_eval
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/abstract/evaluate",
                    {
                        "model": "qwen2.5:14b",
                        "research_need": "I need papers on robust retrieval.",
                        "abstract": "This abstract studies robust retrieval methods.",
                    },
                )
            finally:
                app.evaluate_abstract_relevance = original_eval

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("recommendation"), "download_and_index")
        self.assertEqual(payload.get("confidence"), 88)

    def test_post_pdf_ask_default_hides_debug_trace(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                self.assertFalse(debug_trace)
                return {
                    "ok": True,
                    "answer": "grounded answer",
                    "sources": [],
                }

            app.ask_pdf_library = fake_ask
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "Who was Herbert Hoover?",
                        "model": "qwen2.5:14b",
                        "top_k": 6,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertNotIn("debug_trace", payload)

    def test_post_pdf_ask_debug_trace_opt_in(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                self.assertTrue(debug_trace)
                return {
                    "ok": True,
                    "answer": "grounded answer",
                    "sources": [],
                    "debug_trace": {
                        "enabled": True,
                        "top_k": top_k,
                        "retrieval": [],
                    },
                }

            app.ask_pdf_library = fake_ask
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "Who was Herbert Hoover?",
                        "model": "qwen2.5:14b",
                        "top_k": 6,
                        "debug_trace": True,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertIn("debug_trace", payload)
        self.assertTrue(payload["debug_trace"].get("enabled"))

    def test_post_pdf_ask_contract_includes_structured_fields(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                return {
                    "ok": True,
                    "answer": "Herbert Hoover was president during the onset of the Great Depression.",
                    "sources": [
                        {
                            "path": "C:/library/us-history.pdf",
                            "title": "US History",
                            "location": 12,
                            "location_type": "page",
                            "page": 12,
                            "score": 2.345,
                        }
                    ],
                }

            app.ask_pdf_library = fake_ask
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "Who was Herbert Hoover?",
                        "model": "qwen2.5:14b",
                        "top_k": 6,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertIn("answer", payload)
        self.assertIn("answer_text", payload)
        self.assertIn("sources", payload)
        self.assertIn("citations", payload)
        self.assertEqual(payload.get("answer_text"), payload.get("answer"))
        self.assertIsInstance(payload.get("citations"), list)
        self.assertEqual(len(payload.get("citations")), 1)
        self.assertEqual(payload["citations"][0].get("citation_id"), "c1")
        self.assertEqual(payload["citations"][0].get(
            "path"), "C:/library/us-history.pdf")
        self.assertIn("confidence_label", payload["citations"][0])
        self.assertIn("confidence_class", payload["citations"][0])
        self.assertIn("confidence_title", payload["citations"][0])

    def test_post_pdf_ask_contract_calibrates_confidence_distribution(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                return {
                    "ok": True,
                    "answer": "Calibrated confidence response.",
                    "sources": [
                        {
                            "path": "C:/library/a.pdf",
                            "title": "Doc A",
                            "location": 3,
                            "location_type": "page",
                            "page": 3,
                            "score": 2.0,
                        },
                        {
                            "path": "C:/library/b.pdf",
                            "title": "Doc B",
                            "location": 4,
                            "location_type": "page",
                            "page": 4,
                            "score": 1.45,
                        },
                        {
                            "path": "C:/library/c.pdf",
                            "title": "Doc C",
                            "location": 7,
                            "location_type": "page",
                            "page": 7,
                            "score": 1.05,
                        },
                    ],
                }

            app.ask_pdf_library = fake_ask
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "confidence distribution test",
                        "model": "qwen2.5:14b",
                        "top_k": 6,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        labels = [
            str(c.get("confidence_label", ""))
            for c in payload.get("citations", [])
        ]
        self.assertIn("High", labels)
        self.assertIn("Medium", labels)
        self.assertIn("Low", labels)

    def test_post_pdf_ask_contract_preserves_existing_structured_payload(self):
        with running_server() as (app, base_url):
            original_ask = app.ask_pdf_library

            def fake_ask(query, model, top_k, include_paths=None, exclude_paths=None, debug_trace=False):
                return {
                    "ok": True,
                    "answer": "legacy answer",
                    "answer_text": "structured answer",
                    "sources": [],
                    "citations": [
                        {
                            "citation_id": "existing-c1",
                            "path": "C:/library/doc.pdf",
                            "location": 9,
                            "confidence_label": "High",
                            "confidence_class": "conf-high",
                            "confidence_title": "Existing confidence metadata",
                        }
                    ],
                }

            app.ask_pdf_library = fake_ask
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/ask",
                    {
                        "query": "test query",
                        "model": "qwen2.5:14b",
                        "top_k": 6,
                    },
                )
            finally:
                app.ask_pdf_library = original_ask

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("answer"), "legacy answer")
        self.assertEqual(payload.get("answer_text"), "structured answer")
        self.assertEqual(payload.get("citations", [])[
                         0].get("citation_id"), "existing-c1")
        self.assertEqual(payload.get("citations", [])[
            0].get("confidence_label"), "High")

    def test_post_pdf_synthesize_returns_sources_and_ok(self):
        with running_server() as (app, base_url):
            original_synth = app.synthesize_pdf_library
            original_validate = app.validate_model_allowed
            app.validate_model_allowed = lambda model: {"ok": True}

            def fake_synth(query, model, top_k, include_paths=None, exclude_paths=None):
                return {
                    "ok": True,
                    "sources": [
                        {
                            "path": "/library/paper.pdf",
                            "title": "Paper",
                            "location": 5,
                            "score": 1.23,
                            "relevancy": "This source is relevant because it covers the topic.",
                        }
                    ],
                }

            app.synthesize_pdf_library = fake_synth
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/synthesize",
                    {
                        "query": "What topics does the library cover?",
                        "model": "qwen2.5:14b",
                        "top_k": 5,
                    },
                )
            finally:
                app.synthesize_pdf_library = original_synth
                app.validate_model_allowed = original_validate

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertIsInstance(payload.get("sources"), list)
        self.assertEqual(len(payload["sources"]), 1)
        self.assertIn("relevancy", payload["sources"][0])

    def test_post_pdf_synthesize_blocked_when_resource_pressure_critical(self):
        with running_server() as (app, base_url):
            original_acquire = app.acquire_generation_slot
            original_validate = app.validate_model_allowed
            app.validate_model_allowed = lambda model: {"ok": True}
            app.acquire_generation_slot = lambda kind: {
                "ok": False,
                "code": 503,
                "error": "System pressure is critical",
                "policy": {"pressure": "critical"},
            }
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/synthesize",
                    {
                        "query": "What does the library cover?",
                        "model": "qwen2.5:14b",
                    },
                )
            finally:
                app.acquire_generation_slot = original_acquire
                app.validate_model_allowed = original_validate

        self.assertEqual(status, 503)
        self.assertFalse(payload.get("ok", True))
        self.assertIn("critical", str(payload.get("error", "")))

    def test_post_pdf_synthesize_rejected_when_model_unsafe(self):
        with running_server() as (app, base_url):
            original_validate = app.validate_model_allowed
            app.validate_model_allowed = lambda model: {
                "ok": False,
                "code": 409,
                "error": f"Model {model!r} exceeds safe resource limits.",
            }
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/pdf/synthesize",
                    {
                        "query": "What does the library cover?",
                        "model": "llama3.1:70b",
                    },
                )
            finally:
                app.validate_model_allowed = original_validate

        self.assertEqual(status, 409)
        self.assertFalse(payload.get("ok", True))
        self.assertIn("safe resource limits", str(payload.get("error", "")))

    def test_api_routes_require_key_when_configured(self):
        with running_server(api_key="secret-key") as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/history")
            self.assertEqual(status, 401)
            self.assertEqual(payload.get("error"), "Unauthorized")

            status, payload, _ = _request_json(
                "GET",
                f"{base_url}/api/history",
                headers={"X-API-Key": "secret-key"},
            )

        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        self.assertIn("messages", payload)


if __name__ == "__main__":
    unittest.main()
