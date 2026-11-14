import time

from lazyresearch.science.execution import execute_isolated
from lazyresearch.science.registry import Registry
from lazyresearch.science.budget import BudgetGovernor
from lazyresearch.science.schemas import ScienceBudget


def fast_worker(root, payload):
    return {"answer": payload["x"] * 2}


def slow_worker(root, payload):
    time.sleep(10)
    return {}


def failing_worker(root, payload):
    raise ValueError("controlled failure")


def test_success_failure_and_reuse(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget(max_single_experiment_seconds=20))
    result = execute_isolated(registry, budget, "e1", fast_worker, {"x": 3})
    assert result["answer"] == 6
    again = execute_isolated(registry, budget, "e1", failing_worker, {})
    assert again == result
    assert budget.snapshot()["experiment_count"] == 1
    failed = execute_isolated(registry, budget, "e2", failing_worker, {})
    assert "controlled failure" in failed["error"]


def test_timeout_is_terminal_and_budget_is_retained(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget(max_single_experiment_seconds=.2))
    result = execute_isolated(registry, budget, "timeout", slow_worker, {})
    assert result["error"] == "experiment_timeout"
    assert budget.snapshot()["experiment_count"] == 1
    assert execute_isolated(registry, budget, "timeout", slow_worker, {}) == result


def test_stop_prevents_new_execution(tmp_path):
    import pytest
    from lazyresearch.science.budget import BudgetExceeded
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    (tmp_path / "stop.requested").touch()
    with pytest.raises(BudgetExceeded, match="user_stop"):
        execute_isolated(registry, budget, "stopped", fast_worker, {"x": 1})
    assert budget.snapshot()["experiment_count"] == 0


def test_reserved_interrupted_operation_is_not_repeated(tmp_path):
    registry = Registry(tmp_path)
    budget = BudgetGovernor(registry, ScienceBudget())
    budget.reserve_experiment("interrupted")
    result = execute_isolated(registry, budget, "interrupted", fast_worker, {"x": 1})
    assert result["error"] == "interrupted_execution_not_repeated"
    assert budget.snapshot()["experiment_count"] == 1


def test_run_lock_prevents_concurrent_execution(tmp_path):
    import pytest
    registry = Registry(tmp_path)
    with registry.claim():
        with pytest.raises(RuntimeError, match="already active"):
            with Registry(tmp_path).claim():
                pass
