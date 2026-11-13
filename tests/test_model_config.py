import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch

from fastapi.testclient import TestClient

from lazyresearch.adapters import FixtureAdapter
from lazyresearch.api import create_app
from lazyresearch.configuration import load_model_config


class DiagnosticFixture(FixtureAdapter):
    def verify(self, results, previous):
        verdict = super().verify(results, previous)
        return verdict.model_copy(update={"recoverable_unknown": not verdict.passed})


class ModelConfigTest(unittest.TestCase):
    def test_cloud_key_in_config_takes_precedence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "models.toml"
            path.write_text("""
[cloud]
enabled = true
base_url = "https://example.com/v1"
model = "example"
api_key = "file-only-test-value"
api_key_env = "LAZYRESEARCH_TEST_KEY"
[prompts]
planning = "Plan a research task."
""", encoding="utf-8")
            with patch.dict("os.environ", {"LAZYRESEARCH_TEST_KEY": "environment-test-value"}):
                runner = load_model_config(path).runner(path.parent / "state")
                self.assertEqual(runner.gateway.api_key, "file-only-test-value")
                self.assertNotIn("file-only-test-value", json.dumps(runner.model_status))

    def test_research_request_over_both_http_endpoints(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), body))
                content = (
                    {"summary": "Check evidence and revise", "steps": ["Collect evidence", "Verify a revision"]}
                    if body["model"] == "large" else {"action_id": "failure"}
                )
                response = json.dumps({
                    "choices": [{"message": {"content": json.dumps(content)}}],
                    "usage": {"total_tokens": 31},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):
                pass

        with TemporaryDirectory() as directory, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                config = root / "models.toml"
                config.write_text(f"""
[local]
enabled = true
base_url = "http://127.0.0.1:{server.server_port}/local/v1"
model = "small"
[cloud]
enabled = true
base_url = "http://127.0.0.1:{server.server_port}/cloud/v1"
model = "large"
api_key_env = "LAZYRESEARCH_TEST_KEY"
[prompts]
local = "Choose which research candidate to prioritize."
planning = "Produce a structured research plan."
diagnosis = "Choose the corrective experiment."
""", encoding="utf-8")
                with patch.dict("os.environ", {"LAZYRESEARCH_TEST_KEY": "smoke-only"}):
                    runner = load_model_config(config).runner(root / "state", adapters={"fixture": DiagnosticFixture()})
                    with TestClient(create_app(runner=runner)) as client:
                        status = client.get("/config")
                        self.assertTrue(status.json()["models"]["local"]["ready"])
                        self.assertTrue(status.json()["models"]["cloud"]["ready"])
                        self.assertNotIn("smoke-only", status.text)
                        response = client.post("/runs", json={
                            "goal": "Evaluate whether a failed evidence check leads to a verifiable revision",
                            "budget": {"cloud_requests": 1, "tokens": 6000},
                        })
                        self.assertEqual(response.status_code, 202)
                        base = "/runs/" + response.json()["id"]
                        events = client.get(base + "/events")
                        self.assertIn("local_accounted", events.text)
                        self.assertIn("cloud_accounted", events.text)
                        state = client.get(base).json()
                        self.assertEqual((state["stop_reason"], state["round"]), ("validated", 2))
                        self.assertEqual(state["plan"]["steps"], ["Collect evidence", "Verify a revision"])
                        self.assertEqual(state["plan_source"], "cloud")
                        self.assertEqual(state["results"][0]["candidate_id"], "failure")
                        self.assertEqual((state["local_requests"], state["local_tokens"]), (1, 31))
                        self.assertEqual((state["cloud_requests"], state["tokens"]), (1, 31))
                        self.assertEqual(client.get(base + "/artifacts").status_code, 200)
                self.assertEqual([item[:2] for item in requests], [
                    ("/cloud/v1/chat/completions", "Bearer smoke-only"),
                    ("/local/v1/chat/completions", None),
                ])
                self.assertIn("Verify a revision", requests[1][2]["messages"][1]["content"])
                self.assertTrue(all(not item[2]["stream"] for item in requests))
            finally:
                server.shutdown()
                thread.join()
