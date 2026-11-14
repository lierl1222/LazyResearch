import json
import tempfile
import unittest
from pathlib import Path

import httpx

from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.tools.cpu import Benchmark, membership
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.gateway import ScienceGateway
from lazyresearch.science.registry import Registry


class ResearchTests(unittest.TestCase):
    def test_favorita_director_uses_scores_and_locks_the_best_candidate(self):
        from unittest.mock import patch

        class Gateway:
            config = ModelConfig(local={"enabled": True, "base_url": "http://example.test", "model": "test"})

            def ask(self, role, id, instruction, context, schema):
                if schema.__name__ != "ForecastChoice":
                    return schema(action="finish", objective_or_conclusion="结束")
                round_number = len(context["attempted"])
                if round_number == 1:
                    self_test.assertEqual(context["best"]["candidate"], .44)
                    if "rejected_duplicate" not in context:
                        return schema(weeks=8, method="weekday_log_median", use_promotion=False,
                                      hypothesis="模型第一次重复了已试方案")
                    self_test.assertEqual(context["rejected_duplicate"]["weeks"], 8)
                if round_number == 2:
                    self_test.assertEqual(context["best"]["candidate"], .39)
                return schema(weeks=8 + round_number, method="weekday_log_median",
                              use_promotion=False, hypothesis="调整训练窗口")

        self_test = self
        with tempfile.TemporaryDirectory() as folder:
            registry = Registry(Path(folder))
            task = Task(goal="预测 Favorita 销量", max_delegations=3, budget={"max_experiments": 4})
            budget = BudgetGovernor(registry, task.budget)
            calls, events = [], []

            def execute(registry, budget, id, worker, payload):
                args = payload["arguments"]
                calls.append((id, args["weeks"], args["method"]))
                budget.reserve_experiment(id)
                budget.settle_experiment(id, 0)
                if id == "favorita-final":
                    self.assertEqual([trial["candidate"] for trial in payload["trials"]], [.44, .39, .41])
                    return {"candidate": .46, "baseline": .62, "metric": "RMSLE", "verdict": "supported"}
                score = {8: .44, 9: .39, 10: .41}[args["weeks"]]
                return {"candidate": score, "baseline": .55, "metric": "RMSLE", "verdict": "supported"}

            material = {**task.model_dump(), "favorita_files": True, "csv_files": True}
            with patch("lazyresearch.forecast_search.execute_isolated", side_effect=execute):
                result = research(task, material, registry, Gateway(), budget,
                                  lambda stage, **details: events.append((stage, details)))

            self.assertEqual([weeks for _, weeks, _ in calls], [8, 9, 10, 9])
            self.assertEqual(calls[-1][0], "favorita-final")
            self.assertTrue(any(stage == "revision" and event["round"] == 2 for stage, event in events))
            self.assertEqual(result["status"], "reported")
            self.assertIn("worker-1-0", result["citations"])

    def test_worker_revises_using_counterexample_then_director_cites_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Registry(Path(folder))
            task = Task(goal="Infer polynomial", sequence=[1, 2, 5, 10])
            task.budget.max_experiments = 2
            budget = BudgetGovernor(registry, task.budget)
            config = ModelConfig()
            config.local.enabled = True
            config.local.base_url = "http://example.test"
            config.local.model = "test"
            config.local.max_output_tokens = 200
            calls = []

            def respond(request):
                prompt = json.loads(json.loads(request.content)["messages"][1]["content"])
                calls.append(prompt)
                n = len(calls)
                if n == 1:
                    answer = dict(action="delegate", objective_or_conclusion="Test candidate polynomials")
                elif n in (2, 3):
                    if n == 3:
                        self.assertEqual(prompt["history"][0]["validation"]["n"], 2)
                    answer = dict(action="experiment", hypothesis_or_finding="Polynomial fit",
                                  prediction_or_limitation="All supplied values match", tool="sequence",
                                  arguments={"coefficients": [1, 1] if n == 2 else [1, 0, 1]})
                elif n == 4:
                    self.assertEqual(prompt["history"][-1]["validation"]["verdict"], "supported")
                    answer = dict(action="return", hypothesis_or_finding="1+n squared", prediction_or_limitation="finite range")
                else:
                    answer = dict(action="finish", objective_or_conclusion="1+n squared on indices 0..3",
                                  evidence=["worker-0-1"])
                return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(answer)}}],
                                                 "usage":{"prompt_tokens":100,"completion_tokens":30}})
            gateway = ScienceGateway(config, registry, budget, httpx.MockTransport(respond), allow_reporting=True)
            report = research(task, task.model_dump(), registry, gateway, budget)
            self.assertEqual(report["status"], "reported", report)
            self.assertEqual(report["budget"]["experiment_count"], 2)
            self.assertEqual(report["budget"]["llm_calls"], 4)

    def test_finish_is_provisional_while_distinct_trials_fit(self):
        class Gateway:
            config = ModelConfig(local={"enabled": True, "base_url": "http://fixture", "model": "test"})
            def ask(self,role,id,instruction,context,schema):
                if schema.__name__ == "Direction":
                    return schema(action="finish",objective_or_conclusion="interim",
                                  evidence=list(context["observations"]))
                if context["history"]:
                    return schema(action="return",hypothesis_or_finding="recorded",prediction_or_limitation="finite")
                n=int(id.split("-")[1])
                return schema(action="experiment",tool="sequence",arguments={"coefficients":[1,n]},
                              hypothesis_or_finding="compare slope",prediction_or_limitation="finite")
        with tempfile.TemporaryDirectory() as folder:
            registry=Registry(Path(folder))
            task=Task(goal="Compare slopes",sequence=[1,2,3],max_delegations=3,budget={"max_experiments":3})
            report=research(task,task.model_dump(),registry,Gateway(),BudgetGovernor(registry,task.budget))
            self.assertEqual(report["budget"]["experiment_count"],3)
            self.assertEqual(len(report["evidence"]),3)
            self.assertEqual(report["status"],"reported")

    def test_benchmark_returns_paired_timings(self):
        result = membership(None, {"seed":42,"target_speedup":1.2}, Benchmark(method="set"))
        self.assertEqual(len(result["baseline_ns"]), 7)
        self.assertGreater(result["speedup"], 0)

    def test_local_context_overflow_retries_with_compact_evidence(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            registry = Registry(Path(folder))
            task = Task(goal="检查数据", domain="数据分析")
            budget = BudgetGovernor(registry, task.budget)
            config = ModelConfig(local={"enabled": True, "base_url": "http://example.test", "model": "test"})
            requests, events = [], []

            def respond(request):
                body = json.loads(request.content)
                context = json.loads(body["messages"][1]["content"])
                if "registry" in context:
                    self.assertIn("read_material", context["registry"])
                    decision = {"objective":"读取数据","tools":["read_material"]}
                    return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(decision)}}]})
                requests.append(context)
                if len(requests) == 1:
                    decision = {"action": "delegate", "objective_or_conclusion": "读取数据"}
                elif len(requests) == 2:
                    decision = {"action": "experiment", "hypothesis_or_finding": "检查材料",
                                "prediction_or_limitation": "核对内容", "tool": "read_material"}
                elif len(requests) == 3:
                    decision = {"action": "return", "hypothesis_or_finding": "已读取",
                                "prediction_or_limitation": "仅限所给材料"}
                elif len(requests) == 4:
                    return httpx.Response(400, json={"error": {"message": "request exceeds the available context size"}})
                else:
                    self.assertEqual(context["observations"]["worker-0-0"]["verdict"], "observed")
                    self.assertLess(len(body["messages"][1]["content"]),
                                    len(json.dumps(requests[-2], ensure_ascii=False)) / 2)
                    decision = {"action": "finish", "objective_or_conclusion": "已核对材料",
                                "evidence": ["worker-0-0"]}
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision)}}]})

            gateway = ScienceGateway(config, registry, budget, httpx.MockTransport(respond), allow_reporting=True)
            with patch("lazyresearch.research.execute_isolated",
                       return_value={"verdict": "observed", "match": False, "query": "检" * 1200}):
                result = research(task, task.model_dump(), registry, gateway, budget,
                                  lambda stage, **_: events.append(stage))
            self.assertEqual(result["status"], "reported", result)
            self.assertIn("revision", events)
            self.assertEqual(registry.get("model_calls", "director-1-local")["error"], "ModelContextExceeded")
            self.assertTrue(registry.get("model_calls", "director-1-local-compact")["decision"])
