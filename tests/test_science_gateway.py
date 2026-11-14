import httpx
import pytest

from lazyresearch.configuration import ModelConfig
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.registry import Registry
from lazyresearch.science.schemas import ScienceBudget
from lazyresearch.science.gateway import ScienceGateway, Selection


def test_actual_usage_and_decision_cached(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid/v1", "model": "test"}})
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"hypothesis_id":"h1","reason":"evidence"}'}}],
                                         "usage": {"prompt_tokens": 23, "completion_tokens": 12}})
    gateway = ScienceGateway(config, registry, budget, transport=httpx.MockTransport(handle))
    result = gateway.ask("cloud", "plan", "Decide", {"ids": ["h1"]}, Selection)
    assert result.hypothesis_id == "h1"
    assert gateway.ask("cloud", "plan", "Decide", {}, Selection) == result
    assert len(requests) == 1
    assert budget.snapshot()["input_tokens"] == 23
    assert budget.snapshot()["output_tokens"] == 12


def test_failed_request_keeps_reservation_and_no_retry(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test"}})
    gateway = ScienceGateway(config, registry, budget, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(RuntimeError):
        gateway.ask("cloud", "failed", "Decide", {}, Selection)
    assert budget.snapshot()["unknown_usage_calls"] == 1
    with pytest.raises(RuntimeError):
        gateway.ask("cloud", "failed", "Decide", {}, Selection)
    assert budget.snapshot()["llm_calls"] == 1


def test_total_request_deadline_is_bounded(tmp_path):
    import asyncio
    import time
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test", "timeout_seconds": .05}})
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(503)
    gateway = ScienceGateway(config, registry, budget, transport=httpx.MockTransport(slow))
    started = time.perf_counter()
    with pytest.raises(RuntimeError):
        gateway.ask("cloud", "slow", "Decide", {}, Selection)
    assert time.perf_counter() - started < .5
    assert registry.get("model_calls", "slow")["error"] == "TimeoutError"


def test_configured_pricing_accounts_actual_tokens(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget(max_api_cost_usd=.1))
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test",
                                                   "input_price_per_million": 1, "output_price_per_million": 2}})
    payload = {"choices": [{"message": {"content": '{"hypothesis_id":"h","reason":"r"}'}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
    gateway = ScienceGateway(config, registry, budget, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    gateway.ask("cloud", "priced", "Choose", {}, Selection)
    assert budget.snapshot()["api_cost_usd"] == pytest.approx(.00012)


def test_cloud_plan_selects_only_executable_hypotheses(tmp_path):
    from lazyresearch.science.graph import ScienceRunner
    from lazyresearch.science.schemas import TaskConfig
    task = TaskConfig.model_validate({"dataset": {"path": "unused.csv", "target": "y"},
                                     "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test"}})
    runner = ScienceRunner(tmp_path, task, config)
    runner.registry.put("profile", {"id": "dataset-profile", "features": ["a", "b"]})
    payload = {"choices": [{"message": {"content": '{"summary":"Test nonlinear alternatives","hypothesis_ids":["h-nonlinear_model","h-feature_interaction"]}'}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    runner.gateway.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    assert runner.hypothesize({})["next_template"] == "nonlinear_model"
    assert len(runner.registry.list("hypotheses")) == 2
    assert all(h["observations"] == ["dataset-profile"] for h in runner.registry.list("hypotheses"))


def test_user_stop_cancels_active_request(tmp_path):
    import asyncio
    import time
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    config = ModelConfig.model_validate({"cloud": {"enabled": True, "base_url": "https://test.invalid", "model": "test", "timeout_seconds": 5}})
    async def slow(request):
        (tmp_path / "stop.requested").touch()
        await asyncio.sleep(2)
        return httpx.Response(503)
    gateway = ScienceGateway(config, registry, budget, transport=httpx.MockTransport(slow))
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="UserStopped"):
        gateway.ask("cloud", "stop", "Choose", {}, Selection)
    assert time.perf_counter() - started < 1
    assert budget.snapshot()["unknown_usage_calls"] == 1


def test_local_model_selects_next_executable_hypothesis(tmp_path):
    from lazyresearch.science.graph import ScienceRunner
    from lazyresearch.science.schemas import TaskConfig
    from lazyresearch.science.agents import HypothesisScientist
    task = TaskConfig.model_validate({"dataset": {"path": "unused", "target": "y"}, "llm": {"provider": "configured_api"}})
    config = ModelConfig.model_validate({"local": {"enabled": True, "base_url": "http://local.invalid", "model": "small"}})
    runner = ScienceRunner(tmp_path, task, config)
    for h in HypothesisScientist().propose({"id": "p", "features": ["a", "b"]}):
        runner.registry.put("hypotheses", h.model_dump(), h.id)
    runner.registry.put("reviews", {"id": "review-e1", "verdict": "reject"}, "review-e1")
    runner.registry.put("experiments", {"experiment_id": "e1", "metrics": {}}, "e1")
    payload = {"choices": [{"message": {"content": '{"hypothesis_id":"h-class_imbalance","reason":"Compare weighting after unsupported interaction"}'}}],
               "usage": {"prompt_tokens": 50, "completion_tokens": 20}}
    runner.gateway.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    update = runner.decide({"iteration": 1, "stalled": 1, "completed_templates": ["feature_interaction"], "current_experiment": "e1"})
    assert update["next_template"] == "class_imbalance"
    assert runner.registry.get("model_calls", "selection-1")["role"] == "local"
    assert "review-e1" in runner.registry.get("hypotheses", "h-class_imbalance")["observations"]
