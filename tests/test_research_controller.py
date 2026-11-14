import json
import tempfile
import unittest
from pathlib import Path

import httpx

from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.research_tools import Benchmark, membership
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.gateway import ScienceGateway
from lazyresearch.science.registry import Registry


class ResearchTests(unittest.TestCase):
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
            self.assertEqual(report["budget"]["llm_calls"], 5)

    def test_benchmark_returns_paired_timings(self):
        result = membership(None, {"seed":42,"target_speedup":1.2}, Benchmark(method="set"))
        self.assertEqual(len(result["baseline_ns"]), 7)
        self.assertGreater(result["speedup"], 0)
