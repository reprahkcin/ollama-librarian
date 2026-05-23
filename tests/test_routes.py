import json
import unittest
from urllib.request import Request, urlopen

from tests.helpers.server_harness import running_server


def _request_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict | list, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
        return resp.status, parsed, dict(resp.headers)


class RouteBaselineTests(unittest.TestCase):
    def test_get_history_returns_messages_payload(self):
        with running_server() as (_, base_url):
            status, payload, headers = _request_json("GET", f"{base_url}/api/history")

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
                {"role": "user", "text": "phase-0 check", "ts": "2026-05-22T00:00:00Z"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True})

            status, history, _ = _request_json("GET", f"{base_url}/api/history")

        self.assertEqual(status, 200)
        self.assertIsInstance(history, dict)
        self.assertIsInstance(history.get("messages"), list)
        self.assertEqual(len(history["messages"]), 1)
        self.assertEqual(history["messages"][0].get("role"), "user")
        self.assertEqual(history["messages"][0].get("text"), "phase-0 check")


if __name__ == "__main__":
    unittest.main()
