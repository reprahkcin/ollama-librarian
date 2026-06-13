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

    def test_post_generate_requires_model(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "POST", f"{base_url}/api/generate", {"prompt": "hello"}
            )

        self.assertEqual(status, 400)
        self.assertIsInstance(payload, dict)
        self.assertIn("model", str(payload.get("error", "")).lower())

    def test_post_generate_trips_model_guard_after_repeated_failures(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_MODEL_FAILURE_THRESHOLD": "2",
                "OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS": "120",
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
            }
        ) as (app, base_url):
            call_count = {"urlopen": 0}
            original_urlopen = app.urlopen

            def fake_urlopen(_req, timeout=0):
                call_count["urlopen"] += 1
                raise app.URLError("connection reset by peer")

            app.urlopen = fake_urlopen
            try:
                status_1, payload_1, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "unstable-model", "prompt": "test one", "stream": False},
                )
                status_2, payload_2, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "unstable-model", "prompt": "test two", "stream": False},
                )
                status_3, payload_3, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "unstable-model",
                        "prompt": "test three", "stream": False},
                )
            finally:
                app.urlopen = original_urlopen

        self.assertEqual(status_1, 502)
        self.assertIsInstance(payload_1, dict)
        self.assertFalse(payload_1.get("guarded", False))

        self.assertEqual(status_2, 503)
        self.assertIsInstance(payload_2, dict)
        self.assertTrue(payload_2.get("guarded"))
        self.assertGreater(int(payload_2.get("retry_after_seconds", 0)), 0)

        self.assertEqual(status_3, 503)
        self.assertIsInstance(payload_3, dict)
        self.assertTrue(payload_3.get("guarded"))
        self.assertGreater(int(payload_3.get("retry_after_seconds", 0)), 0)

        self.assertEqual(call_count["urlopen"], 2)

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

    def test_metrics_endpoint_reports_request_data(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/history")
            self.assertEqual(status, 200)

            status, metrics, _ = _request_json(
                "GET", f"{base_url}/api/metrics?limit=25")

        self.assertEqual(status, 200)
        self.assertTrue(metrics.get("ok"))
        self.assertTrue(metrics.get("enabled"))
        self.assertIn("requests_total", metrics)
        self.assertGreaterEqual(int(metrics.get("requests_total", 0)), 1)
        self.assertIn("recent_requests", metrics)
        self.assertIsInstance(metrics.get("recent_requests"), list)
        self.assertIn("last_resource", metrics)
        self.assertIsInstance(metrics.get("last_resource"), dict)
        resource = metrics.get("last_resource", {})
        self.assertIn("cpu_usage_pct_now", resource)
        self.assertIn("gpu_monitoring", resource)
        self.assertIn("cooldown", metrics)
        self.assertIn("safety_brake", metrics)

    def test_safety_brake_sets_cooldown_from_metrics_snapshot(self):
        with running_server() as (app, base_url):
            original_resource_snapshot = app._resource_snapshot

            def fake_resource_snapshot():
                return {
                    "ts": 0,
                    "cpu_load_pct_1m": 10.0,
                    "cpu_usage_pct_now": 25.0,
                    "cpu_count": 8,
                    "mem_available_mb": 16000.0,
                    "process_rss_mb": 300.0,
                    "disk_free_mb": 100000.0,
                    "gpu_monitoring": "ok",
                    "gpu_present": True,
                    "gpu_count": 1,
                    "gpu_util_pct_max": 97.0,
                    "gpu_mem_util_pct_max": 96.0,
                    "gpu_temp_c_max": 84.0,
                }

            app._resource_snapshot = fake_resource_snapshot
            try:
                status, metrics, _ = _request_json(
                    "GET", f"{base_url}/api/metrics?limit=10")
            finally:
                app._resource_snapshot = original_resource_snapshot

        self.assertEqual(status, 200)
        self.assertTrue(metrics.get("ok"))
        cooldown = metrics.get("cooldown", {})
        self.assertTrue(cooldown.get("active"))
        self.assertIn("Auto safety brake", str(cooldown.get("reason", "")))
        self.assertIn("safety_brake", metrics)

    def test_safety_brake_blocks_generate_before_upstream_call(self):
        with running_server() as (app, base_url):
            original_resource_snapshot = app._resource_snapshot
            original_urlopen = app.urlopen
            call_count = {"urlopen": 0}

            def fake_resource_snapshot():
                return {
                    "ts": 0,
                    "cpu_load_pct_1m": 8.0,
                    "cpu_usage_pct_now": 20.0,
                    "cpu_count": 8,
                    "mem_available_mb": 16000.0,
                    "process_rss_mb": 320.0,
                    "disk_free_mb": 100000.0,
                    "gpu_monitoring": "ok",
                    "gpu_present": True,
                    "gpu_count": 1,
                    "gpu_util_pct_max": 98.0,
                    "gpu_mem_util_pct_max": 97.0,
                    "gpu_temp_c_max": 85.0,
                }

            def fake_urlopen(_req, timeout=0):
                call_count["urlopen"] += 1
                raise app.URLError("should not be called")

            app._resource_snapshot = fake_resource_snapshot
            app.urlopen = fake_urlopen
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "qwen2.5:14b", "prompt": "test", "stream": False},
                )
            finally:
                app._resource_snapshot = original_resource_snapshot
                app.urlopen = original_urlopen

        self.assertEqual(status, 429)
        self.assertIn("safety brake", str(payload.get("error", "")).lower())
        self.assertEqual(call_count["urlopen"], 0)

    def test_soft_throttle_delays_generate_under_pressure(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
                "OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "1",
                "OLLAMA_WEB_SOFT_THROTTLE_START_RATIO_PCT": "50",
                "OLLAMA_WEB_SOFT_THROTTLE_MAX_DELAY_MS": "1200",
                "OLLAMA_WEB_SOFT_THROTTLE_MIN_GAP_MS": "0",
            }
        ) as (app, base_url):
            original_resource_snapshot = app._resource_snapshot
            original_urlopen = app.urlopen
            original_sleep = app.time.sleep
            sleep_calls: list[float] = []

            def fake_resource_snapshot():
                return {
                    "ts": 0,
                    "cpu_load_pct_1m": 12.0,
                    "cpu_usage_pct_now": 72.0,
                    "cpu_count": 8,
                    "mem_available_mb": 16000.0,
                    "process_rss_mb": 300.0,
                    "disk_free_mb": 100000.0,
                    "gpu_monitoring": "unavailable",
                    "gpu_present": False,
                }

            def fake_urlopen(_req, timeout=0):
                raise app.URLError("simulated upstream timeout")

            def fake_sleep(seconds):
                sleep_calls.append(float(seconds))

            app._resource_snapshot = fake_resource_snapshot
            app.urlopen = fake_urlopen
            app.time.sleep = fake_sleep
            try:
                status, _, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "qwen2.5:14b", "prompt": "test", "stream": False},
                )
            finally:
                app._resource_snapshot = original_resource_snapshot
                app.urlopen = original_urlopen
                app.time.sleep = original_sleep

        self.assertIn(status, {502, 503})
        self.assertTrue(sleep_calls)
        self.assertGreater(sleep_calls[0], 0.0)

    def test_heavy_operation_guard_rejects_when_busy(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_HEAVY_SERIAL_ENABLED": "1",
                "OLLAMA_WEB_HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS": "1",
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
                "OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "0",
            }
        ) as (app, base_url):
            acquired = app.HEAVY_OP_LOCK.acquire(timeout=1.0)
            self.assertTrue(acquired)

            with app.HEAVY_OP_STATE_LOCK:
                app.HEAVY_OP_STATE["active"] = True
                app.HEAVY_OP_STATE["active_operation"] = "PDF-grounded ask"
                app.HEAVY_OP_STATE["active_since_ts"] = int(app.time.time())

            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "qwen2.5:14b", "prompt": "test", "stream": False},
                )
            finally:
                with app.HEAVY_OP_STATE_LOCK:
                    app.HEAVY_OP_STATE["active"] = False
                    app.HEAVY_OP_STATE["active_operation"] = ""
                    app.HEAVY_OP_STATE["active_since_ts"] = None
                app.HEAVY_OP_LOCK.release()

        self.assertEqual(status, 429)
        self.assertIn("heavy operation", str(payload.get("error", "")).lower())
        self.assertEqual(int(payload.get("retry_after_seconds", 0) or 0), 1)
        self.assertTrue(
            bool(payload.get("heavy_operation_guard", {}).get("enabled")))

    def test_metrics_exposes_heavy_operation_guard(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET",
                f"{base_url}/api/metrics?limit=10",
            )

        self.assertEqual(status, 200)
        self.assertIn("heavy_operation_guard", payload)
        self.assertIsInstance(payload.get("heavy_operation_guard"), dict)
        self.assertIn("enabled", payload.get("heavy_operation_guard", {}))

    def test_safe_generate_profile_applies_defaults(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED": "1",
                "OLLAMA_WEB_SAFE_GENERATE_NUM_THREAD": "2",
                "OLLAMA_WEB_SAFE_GENERATE_NUM_BATCH": "12",
                "OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP": "320",
                "OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "0",
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
            }
        ) as (app, base_url):
            original_urlopen = app.urlopen
            captured_payload = {}

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"response":"ok"}'

            def fake_urlopen(req, timeout=0):
                body = req.data.decode("utf-8")
                captured_payload.update(json.loads(body))
                return _Resp()

            app.urlopen = fake_urlopen
            try:
                status, payload, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {"model": "qwen2.5:14b", "prompt": "test", "stream": False},
                )
            finally:
                app.urlopen = original_urlopen

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("response"), "ok")
        options = captured_payload.get("options", {})
        self.assertEqual(int(options.get("num_thread", 0)), 2)
        self.assertEqual(int(options.get("num_batch", 0)), 12)
        self.assertEqual(int(options.get("num_predict", 0)), 320)

    def test_safe_generate_profile_caps_num_predict(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED": "1",
                "OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP": "320",
                "OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "0",
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
            }
        ) as (app, base_url):
            original_urlopen = app.urlopen
            captured_payload = {}

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"response":"ok"}'

            def fake_urlopen(req, timeout=0):
                body = req.data.decode("utf-8")
                captured_payload.update(json.loads(body))
                return _Resp()

            app.urlopen = fake_urlopen
            try:
                status, _, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {
                        "model": "qwen2.5:14b",
                        "prompt": "test",
                        "stream": False,
                        "options": {"num_predict": 1024},
                    },
                )
            finally:
                app.urlopen = original_urlopen

        self.assertEqual(status, 200)
        options = captured_payload.get("options", {})
        self.assertEqual(int(options.get("num_predict", 0)), 320)

    def test_safety_brake_cooldown_releases_early_after_recovery(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_SAFETY_BRAKE_MIN_HOLD_SECONDS": "0",
                "OLLAMA_WEB_SAFETY_BRAKE_RELEASE_STREAK": "2",
                "OLLAMA_WEB_SAFETY_BRAKE_GPU_UTIL_PCT": "88",
                "OLLAMA_WEB_SAFETY_BRAKE_GPU_MEM_PCT": "88",
                "OLLAMA_WEB_SAFETY_BRAKE_GPU_TEMP_C": "78",
            }
        ) as (app, base_url):
            original_resource_snapshot = app._resource_snapshot

            def hot_resource_snapshot():
                return {
                    "ts": 0,
                    "cpu_load_pct_1m": 7.0,
                    "cpu_usage_pct_now": 15.0,
                    "cpu_count": 8,
                    "mem_available_mb": 16000.0,
                    "process_rss_mb": 320.0,
                    "disk_free_mb": 100000.0,
                    "gpu_monitoring": "ok",
                    "gpu_present": True,
                    "gpu_count": 1,
                    "gpu_util_pct_max": 96.0,
                    "gpu_mem_util_pct_max": 95.0,
                    "gpu_temp_c_max": 84.0,
                }

            def cool_resource_snapshot():
                return {
                    "ts": 0,
                    "cpu_load_pct_1m": 7.0,
                    "cpu_usage_pct_now": 10.0,
                    "cpu_count": 8,
                    "mem_available_mb": 16500.0,
                    "process_rss_mb": 300.0,
                    "disk_free_mb": 100000.0,
                    "gpu_monitoring": "ok",
                    "gpu_present": True,
                    "gpu_count": 1,
                    "gpu_util_pct_max": 45.0,
                    "gpu_mem_util_pct_max": 40.0,
                    "gpu_temp_c_max": 55.0,
                }

            app._resource_snapshot = hot_resource_snapshot
            try:
                status_1, metrics_1, _ = _request_json(
                    "GET", f"{base_url}/api/metrics?limit=10")
                app._resource_snapshot = cool_resource_snapshot
                status_2, metrics_2, _ = _request_json(
                    "GET", f"{base_url}/api/metrics?limit=10")
                status_3, metrics_3, _ = _request_json(
                    "GET", f"{base_url}/api/metrics?limit=10")
            finally:
                app._resource_snapshot = original_resource_snapshot

        self.assertEqual(status_1, 200)
        self.assertEqual(status_2, 200)
        self.assertEqual(status_3, 200)
        self.assertTrue(metrics_1.get("cooldown", {}).get("active"))
        self.assertTrue(metrics_2.get("cooldown", {}).get("active"))
        self.assertFalse(metrics_3.get("cooldown", {}).get("active"))

    def test_metrics_reset_clears_counters(self):
        with running_server() as (_, base_url):
            status, _, _ = _request_json("GET", f"{base_url}/api/history")
            self.assertEqual(status, 200)

            status, payload, _ = _request_json(
                "POST", f"{base_url}/api/metrics/reset", {}
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))

            status, metrics, _ = _request_json(
                "GET", f"{base_url}/api/metrics?limit=25")

        self.assertEqual(status, 200)
        self.assertEqual(int(metrics.get("requests_error", 0)), 0)
        # One request may be present for /api/metrics itself after reset.
        self.assertLessEqual(int(metrics.get("requests_total", 0)), 2)

    def test_metrics_capture_generate_request_metadata(self):
        with running_server() as (app, base_url):
            original_urlopen = app.urlopen

            def fake_urlopen(_req, timeout=0):
                raise app.URLError("simulated upstream timeout")

            app.urlopen = fake_urlopen
            try:
                status, _, _ = _request_json(
                    "POST",
                    f"{base_url}/api/generate",
                    {
                        "model": "qwen2.5:14b",
                        "prompt": "What are robust retrieval patterns?",
                        "stream": False,
                    },
                )
                self.assertIn(status, {502, 503})

                status, metrics, _ = _request_json(
                    "GET", f"{base_url}/api/metrics?limit=30")
            finally:
                app.urlopen = original_urlopen

        self.assertEqual(status, 200)
        events = metrics.get("recent_requests", [])
        self.assertTrue(events)
        matched = [
            event
            for event in events
            if event.get("path") == "/api/generate" and event.get("method") == "POST"
        ]
        self.assertTrue(matched)
        meta = matched[0].get("meta", {})
        self.assertEqual(meta.get("model"), "qwen2.5:14b")
        self.assertIn("prompt_chars", meta)

    def test_cooldown_status_endpoint_and_clear(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "GET", f"{base_url}/api/cooldown/status"
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("ok"))
            self.assertFalse(payload.get("cooldown", {}).get("active", True))

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/cooldown",
                {"minutes": 2, "reason": "manual cool down"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("active"))

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/cooldown",
                {"action": "clear"},
            )

        self.assertEqual(status, 200)
        self.assertFalse(payload.get("active", True))

    def test_cooldown_blocks_generate_and_pdf_ask(self):
        with running_server() as (_, base_url):
            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/cooldown",
                {"minutes": 2, "reason": "thermal"},
            )
            self.assertEqual(status, 200)
            self.assertTrue(payload.get("active"))

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/generate",
                {"model": "qwen2.5:14b", "prompt": "hello", "stream": False},
            )
            self.assertEqual(status, 429)
            self.assertIn("cooldown", payload)

            status, payload, _ = _request_json(
                "POST",
                f"{base_url}/api/pdf/ask",
                {"query": "hello", "model": "qwen2.5:14b", "top_k": 6},
            )

        self.assertEqual(status, 429)
        self.assertIn("cooldown", payload)

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

            self.assertTrue(Path(app.PDF_SOURCE_OVERRIDE_PATH).is_file())
            self.assertEqual(
                Path(app.PDF_SOURCE_OVERRIDE_PATH).parent,
                Path(app.HISTORY_PATH).parent,
            )

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

    def test_post_abstract_evaluate_uses_normalized_contract(self):
        with running_server(
            extra_env={
                "OLLAMA_WEB_SAFETY_BRAKE_ENABLED": "0",
                "OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "0",
                "OLLAMA_WEB_HEAVY_SERIAL_ENABLED": "0",
            }
        ) as (app, base_url):
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
        with running_server(extra_env={"OLLAMA_WEB_SOFT_THROTTLE_ENABLED": "0"}) as (app, base_url):
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
