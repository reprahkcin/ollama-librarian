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
