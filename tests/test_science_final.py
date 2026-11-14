import json

from lazyresearch.science.data import generate_demo
from lazyresearch.science.schemas import TaskConfig
from lazyresearch.science.graph import ScienceRunner


def test_final_locked_once_and_report_sources(tmp_path):
    path = tmp_path / "data.csv"
    generate_demo(path, rows=180)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"},
                                     "validation": {"bootstrap_samples": 20},
                                     "budget": {"max_experiments": 8, "max_wall_time_seconds": 120}})
    runner = ScienceRunner(tmp_path / "run", task)
    runner.run()
    locked = runner.registry.get("locked_candidate")
    final = runner.registry.get("test_evaluation")
    assert locked and final and not final.get("error")
    assert final["candidate_id"] == locked["experiment_id"]
    assert len(final["predictions"]) == 36
    assert runner.registry.get("test_gate")["status"] == "consumed"
    before = runner.budget.snapshot()["experiment_count"]
    runner.run()
    assert runner.budget.snapshot()["experiment_count"] == before
    manifest = json.loads((runner.root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_evaluations"] == 1
    assert manifest["mode"] == "mock"
    report = (runner.root / "report.md").read_text(encoding="utf-8")
    assert str(final["metrics"]["average_precision"]) in report
    assert "未证实" in report
    assert (runner.root / "best_model.joblib").exists()
    assert (runner.root / "config.resolved.yaml").exists()
    assert (runner.root / "predictions_test.csv").exists()


def test_initialization_counts_cpu_not_experiment_and_low_budget_test_skipped(tmp_path):
    path = tmp_path / "data.csv"
    generate_demo(path, rows=100)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"},
                                     "budget": {"max_experiments": 2, "max_wall_time_seconds": 120}})
    runner = ScienceRunner(tmp_path / "run", task)
    runner.run()
    assert runner.budget.snapshot()["operations"]["initialize-data"]["kind"] == "compute"
    assert runner.registry.get("test_evaluation") is None
    assert runner.registry.get("test_gate") is None
    assert runner.budget.snapshot()["experiment_count"] == 2


def test_consumed_gate_cannot_reopen_test_after_crash(tmp_path):
    import pytest
    from lazyresearch.science.finalize import final_worker
    from lazyresearch.science.registry import Registry
    registry = Registry(tmp_path)
    registry.put("locked_candidate", {"experiment_id": "e1"})
    registry.put("test_gate", {"status": "consumed", "candidate_id": "e1"})
    cfg = TaskConfig.model_validate({"dataset": {"path": "must-not-open.csv", "target": "y"}})
    with pytest.raises(ValueError, match="already consumed"):
        final_worker(tmp_path, {"config": cfg.model_dump(), "candidate_id": "e1"})
