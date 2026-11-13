import io
import json
import unittest
import zipfile
import time
from tempfile import TemporaryDirectory
from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from lazyresearch.api import create_app
from lazyresearch.adapters import FixtureAdapter
from lazyresearch.model_gateway import Decision, Prompts
from lazyresearch.models import Budget, Plan, ResearchTask
from lazyresearch.runner import Runner
from lazyresearch.workflow import Workflow


class AmbiguousFixture(FixtureAdapter):
    def plan(self, task):
        return Plan(summary="需要协助规划", needs_help=True)


class FakeGateway:
    def __init__(self, usage=14):
        self.calls = []
        self.usage = usage

    def reserve(self, prompt, context):
        return 30

    def decide(self, prompt, context, timeout, request_id):
        self.calls.append(request_id)
        return Decision(action_id="initial", usage=self.usage)


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runner = Runner(self.root)

    def test_loop_and_replay(self):
        task = ResearchTask(goal="Verify research loop")
        run_id = self.runner.create(task)
        state = self.runner.run(run_id)
        self.assertEqual(state["stop_reason"], "validated")
        self.assertEqual(state["round"], 2)
        self.assertEqual(state["cloud_requests"], 0)
        self.assertTrue(any(result.error for result in state["results"]))
        self.assertTrue(state["revisions"][0].evidence_ids)
        with zipfile.ZipFile(io.BytesIO(self.runner.artifacts(run_id))) as archive:
            replay = ResearchTask.model_validate_json(archive.read("task.json"))
        second = self.runner.run(self.runner.create(replay))
        self.assertEqual(second["validation"], state["validation"])

    def test_tool_budget_preserves_partial_result(self):
        task = ResearchTask(goal="Verify partial result", budget=Budget(tools=1))
        state = self.runner.run(self.runner.create(task))
        self.assertEqual(state["stop_reason"], "tool_budget")
        self.assertEqual(len(state["results"]), 1)

    def test_cloud_admission_and_usage(self):
        for prompt, tokens, usage, requests, used, pending in (
            ("", 30, 14, 0, 0, 0),
            ("test", 29, 14, 0, 0, 0),
            ("test", 30, 14, 1, 14, 0),
            ("test", 30, None, 1, 0, 30),
        ):
            with self.subTest(prompt=prompt, tokens=tokens, usage=usage):
                gateway = FakeGateway(usage)
                runner = Runner(self.root, {"fixture": AmbiguousFixture()}, Prompts(planning=prompt), gateway)
                task = ResearchTask(goal="Check routing", budget=Budget(cloud_requests=1, tokens=tokens))
                state = runner.run(runner.create(task))
                self.assertEqual(state["stop_reason"], "validated")
                self.assertEqual(len(gateway.calls), requests)
                self.assertEqual((state["cloud_requests"], state["tokens"], state["tokens_pending"]),
                                 (requests, used, pending))

    def test_resume_reuses_persisted_tool_result(self):
        run_id = self.runner.create(ResearchTask(goal="Check resume"))
        task = self.runner.storage.get(run_id, "task")
        now = time.time()
        self.runner.storage.put(run_id, "started", now)
        adapter = self.runner.adapters["fixture"]
        workflow = Workflow(adapter, self.runner.storage, Prompts(), None)
        config = {"configurable": {"thread_id": run_id}}
        with SqliteSaver.from_conn_string(str(self.root / "checkpoints.sqlite")) as saver:
            graph = workflow.compile(saver)
            graph.invoke({"run_id": run_id, "task": task, "deadline": now + 120},
                         config, interrupt_before=["candidate"])
        self.runner.storage.put(run_id, "result-initial", {
            "candidate_id": "initial", "summary": "Persisted before checkpoint",
            "data": {}, "error": None, "artifact": "results/initial.json",
        })
        state = Runner(self.root).run(run_id)
        self.assertEqual(state["stop_reason"], "validated")
        self.assertEqual(state["results"][0].summary, "Persisted before checkpoint")

    def test_resume_claim_and_removed_adapter(self):
        run_id = self.runner.create(ResearchTask(goal="Check resume ownership"))
        with self.runner.storage.claim(run_id):
            with self.assertRaisesRegex(RuntimeError, "任务正在执行"):
                Runner(self.root).run(run_id)
        state = Runner(self.root, {}).run(run_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(self.runner.storage.events(run_id)[-1]["status"], "failed")

    def test_api_events_replay_and_export(self):
        with TestClient(create_app(self.root)) as client:
            response = client.post("/runs", json={"goal": "Inspect workflow"})
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["id"]
            stream = client.get(f"/runs/{run_id}/events")
            events = [json.loads(line[6:]) for line in stream.text.splitlines()
                      if line.startswith("data: ")]
            self.assertEqual(events[-1]["status"], "finished")
            resumed = client.get(f"/runs/{run_id}/events",
                                 headers={"Last-Event-ID": str(events[-1]["id"] - 1)})
            self.assertEqual(resumed.text.count("data: "), 1)
            self.assertEqual(client.get(f"/runs/{run_id}/artifacts").status_code, 200)
