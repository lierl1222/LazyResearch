from lazyresearch.science.data import generate_demo
from lazyresearch.science.schemas import TaskConfig
from lazyresearch.science.graph import ScienceRunner


def test_research_loop_real_experiments_and_resume(tmp_path):
    path = tmp_path / "data.csv"
    generate_demo(path, rows=180)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"},
                                     "validation": {"bootstrap_samples": 20},
                                     "budget": {"max_llm_calls": 0, "max_experiments": 6, "max_wall_time_seconds": 120}})
    runner = ScienceRunner(tmp_path / "run", task)
    final = runner.run()
    assert final["stop_reason"]
    experiments = runner.registry.list("experiments")
    assert len([e for e in experiments if not e.get("error")]) >= 3
    assert len(runner.registry.list("hypotheses")) >= 2
    assert runner.registry.list("decisions")
    assert all(e["hypothesis_id"] and e["config_hash"] for e in experiments)
    count = runner.budget.snapshot()["experiment_count"]
    assert ScienceRunner(tmp_path / "run", task).run() == final
    assert runner.budget.snapshot()["experiment_count"] == count


def test_zero_budget_still_exports(tmp_path):
    path = tmp_path / "data.csv"
    generate_demo(path, rows=100)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"},
                                     "budget": {"max_experiments": 0, "max_llm_calls": 0}})
    runner = ScienceRunner(tmp_path / "run", task)
    result = runner.run()
    assert result["stop_reason"] == "experiment_budget"
    assert not runner.registry.list("experiments")
    assert (tmp_path / "run" / "report.md").exists()


def test_transient_failure_keeps_checkpoint_resumable(tmp_path, monkeypatch):
    path = tmp_path / "data.csv"
    generate_demo(path, rows=100)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"}, "budget": {"max_experiments": 0}})
    runner = ScienceRunner(tmp_path / "run", task)
    original = runner.initialize
    def fail(state):
        raise RuntimeError("transient")
    fail.__name__ = "initialize"
    monkeypatch.setattr(runner, "initialize", fail)
    assert runner.run()["stop_reason"] == "execution_error"
    assert runner.registry.get("final") is None
    monkeypatch.setattr(runner, "initialize", original)
    assert runner.run()["stop_reason"] == "experiment_budget"


def test_invalid_dataset_error_is_not_dropped(tmp_path):
    task = TaskConfig.model_validate({"dataset": {"path": str(tmp_path / "missing.csv"), "target": "y"}})
    result = ScienceRunner(tmp_path / "run", task).run()
    assert result["stop_reason"] == "invalid_dataset_or_initialization"
    assert "FileNotFoundError" in result["error"]
