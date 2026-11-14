import json
from pathlib import Path
from unittest.mock import patch

from lazyresearch.configuration import ModelConfig
from lazyresearch.research import Task, research
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.registry import Registry
from lazyresearch.tools.topk import ASSETS


def make_material():
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    return {"files": [{"archive_path": name, "id": name, "name": name} for name in manifest]}


def patched_prepare(root, task):
    project = Path(root) / "topk"
    candidate = project / "src" / "candidate.hpp"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("// original\n", encoding="utf8")
    return project, candidate


def fake_review(ask, registry, emit, id, goal, hypothesis, outcome, *, prior=(), round=1):
    return {"id": id, "status": "completed", "summary": "核对", "limitations": "有限",
            "next_step": "继续", "action": "validate"}


def fake_execute(registry, budget, key, fn, payload):
    return {"verdict": "observed", "correctness": 1.0,
            "geomean_speedup_vs_strong": 1.0 + 0.01 * len(key)}


def run_topk_research(tmp_path, pick):
    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="optimize topk", tools=["topk_benchmark"])
            if schema.__name__ == "CandidateChoice":
                return schema(candidate=pick(context, id), hypothesis="try " + (pick(context, id) or ""))
            raise AssertionError(f"unexpected schema {schema.__name__}")

    registry = Registry(tmp_path)
    task = Task(goal="优化 Top-K 算子", domain="算子优化", max_delegations=13)
    budget = BudgetGovernor(registry, task.budget)
    with patch("lazyresearch.tools.topk.prepare", patched_prepare), \
         patch("lazyresearch.science.execution.execute_isolated", fake_execute), \
         patch("lazyresearch.research_review.review_evidence", fake_review):
        return research(task, {**task.model_dump(), **make_material()}, registry, Gateway(), budget)


def test_invalid_candidate_is_repaired_and_research_continues(tmp_path):
    def pick(context, id):
        if "-repair" in id:
            return context["candidates"][0]
        if id.startswith("topk-director-1-"):
            return "initial"
        if id.startswith("topk-director-2-"):
            return "bogus"
        return context["candidates"][0]

    report = run_topk_research(tmp_path, pick)
    assert report["status"] == "reported"
    assert "topk-initial" in report["evidence"]
    assert "topk-candidate" in report["evidence"]
    assert "bogus" not in report["evidence"]
    assert len(report["evidence"]) >= 12


def test_invalid_candidate_falls_back_deterministically(tmp_path):
    def pick(context, id):
        return "bogus"

    report = run_topk_research(tmp_path, pick)
    assert report["status"] == "reported"
    assert "topk-initial" in report["evidence"]
    assert len(report["evidence"]) >= 12


def test_model_failure_falls_back_deterministically(tmp_path):
    class Gateway:
        config = ModelConfig(local={"enabled": True, "base_url": "http://test", "model": "fixture"})

        def ask(self, role, id, instruction, context, schema):
            if schema.__name__ == "CapabilityPlan":
                return schema(objective="optimize topk", tools=["topk_benchmark"])
            raise RuntimeError("ConnectError")

    registry = Registry(tmp_path)
    task = Task(goal="优化 Top-K 算子", domain="算子优化", max_delegations=13)
    budget = BudgetGovernor(registry, task.budget)
    with patch("lazyresearch.tools.topk.prepare", patched_prepare), \
         patch("lazyresearch.science.execution.execute_isolated", fake_execute), \
         patch("lazyresearch.research_review.review_evidence", fake_review):
        report = research(task, {**task.model_dump(), **make_material()}, registry, Gateway(), budget)
    assert report["status"] == "reported"
    assert len(report["evidence"]) >= 12
