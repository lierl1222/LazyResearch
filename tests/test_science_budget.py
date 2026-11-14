import pytest

from lazyresearch.science.budget import BudgetGovernor, BudgetExceeded
from lazyresearch.science.registry import Registry
from lazyresearch.science.schemas import ScienceBudget


def test_reservations_survive_restart_and_unknown_usage(tmp_path):
    registry = Registry(tmp_path)
    limits = ScienceBudget(max_llm_calls=1, max_llm_input_tokens=100, max_llm_output_tokens=50)
    governor = BudgetGovernor(registry, limits)
    governor.reserve_llm("call1", 70, 30)
    governor.settle_llm("call1", None, None)
    restored = BudgetGovernor(Registry(tmp_path), limits)
    assert restored.snapshot()["input_tokens"] == 70
    assert restored.snapshot()["output_tokens"] == 30
    assert restored.snapshot()["unknown_usage_calls"] == 1
    with pytest.raises(BudgetExceeded):
        restored.reserve_llm("call2", 1, 1)


def test_experiment_budget_and_actual_usage(tmp_path):
    governor = BudgetGovernor(Registry(tmp_path), ScienceBudget(max_experiments=1, max_cpu_seconds=5))
    allowance = governor.reserve_experiment("e1")
    assert allowance <= 5
    governor.settle_experiment("e1", 2.5)
    assert governor.snapshot()["cpu_seconds"] == 2.5
    with pytest.raises(BudgetExceeded):
        governor.reserve_experiment("e2")


def test_ledger_idempotence_and_usage_overrun_stops(tmp_path):
    governor = BudgetGovernor(Registry(tmp_path), ScienceBudget(max_llm_input_tokens=10))
    governor.reserve_llm("c1", 5, 5)
    governor.settle_llm("c1", 12, 3)
    governor.settle_llm("c1", 12, 3)
    assert governor.snapshot()["input_tokens"] == 12
    with pytest.raises(BudgetExceeded):
        governor.reserve_llm("c2", 1, 1)


def test_zero_compute_and_unpriced_cost_cap_reject(tmp_path):
    governor = BudgetGovernor(Registry(tmp_path), ScienceBudget(max_cpu_seconds=0, max_api_cost_usd=.1))
    with pytest.raises(BudgetExceeded):
        governor.reserve_experiment("e")
    with pytest.raises(BudgetExceeded):
        governor.reserve_llm("c", 1, 1)


def test_api_mode_exhausted_calls_stop_compute_but_mock_zero_calls_allowed(tmp_path):
    api = BudgetGovernor(Registry(tmp_path / "api"), ScienceBudget(max_llm_calls=1), enforce_llm_limits=True)
    api.reserve_llm("c", 1, 1)
    api.settle_llm("c", 1, 1)
    with pytest.raises(BudgetExceeded, match="llm_call_budget"):
        api.reserve_experiment("e")
    mock = BudgetGovernor(Registry(tmp_path / "mock"), ScienceBudget(max_llm_calls=0))
    assert mock.reserve_experiment("e") > 0


def test_exhausted_cpu_prevents_paid_call(tmp_path):
    governor = BudgetGovernor(Registry(tmp_path), ScienceBudget(max_cpu_seconds=1))
    governor.reserve_experiment("e")
    governor.settle_experiment("e", 1)
    with pytest.raises(BudgetExceeded, match="cpu_budget"):
        governor.reserve_llm("c", 1, 1)

def test_default_input_unlimited_still_counts_tokens(tmp_path):
    governor = BudgetGovernor(Registry(tmp_path), ScienceBudget(), enforce_llm_limits=True)
    governor.reserve_llm("long", 1000000, 10)
    governor.settle_llm("long", 150000, 5, 0)
    assert governor.snapshot()["input_tokens"] == 150000
    governor.reserve_llm("followup", 1000000, 10)
