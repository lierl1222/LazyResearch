import numpy as np
import pytest

from lazyresearch.science.data import generate_demo, prepare_dataset
from lazyresearch.science.schemas import TaskConfig
from lazyresearch.science.experiments import ExperimentSpec, run_experiment


def test_real_baselines_and_controlled_templates(tmp_path):
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=240)
    task = TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"}})
    data = prepare_dataset(task)
    for name, model in [("baseline", "dummy"), ("baseline", "logistic"),
                        ("feature_interaction", "logistic"), ("nonlinear_model", "random_forest"),
                        ("class_imbalance", "logistic"), ("segment_discovery", "logistic")]:
        spec = ExperimentSpec(id=name + model, hypothesis_id="h1", experiment_type=name,
                              model_name=model, data_features=list(data.X_train.columns))
        result, pipeline = run_experiment(spec, data, task.objective.top_fraction)
        assert 0 <= result["metrics"]["average_precision"] <= 1
        assert len(result["predictions"]) == len(data.y_validation)
        assert result["cpu_seconds"] >= 0 and result["elapsed_seconds"] > 0
        assert pipeline is not None
        assert result["comparison_scope"] == "validation"


def test_invalid_parameters_and_feature_rejected(tmp_path):
    with pytest.raises(ValueError):
        ExperimentSpec(id="e1", hypothesis_id="h1", experiment_type="nonlinear_model",
                       model_name="random_forest", model_params={"n_estimators": 100000})
    with pytest.raises(ValueError):
        ExperimentSpec(id="e1", hypothesis_id="h1", experiment_type="baseline",
                       model_name="shell")
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=120)
    data = prepare_dataset(TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y"}}))
    with pytest.raises(ValueError, match="features"):
        run_experiment(ExperimentSpec(id="e1", hypothesis_id="h1", data_features=["duration"]), data, .2)


def test_metrics_top_fraction_matches_prediction_ranking():
    from lazyresearch.science.experiments import metrics
    result = metrics(np.array([0, 1, 0, 1, 0]), np.array([.1, .9, .4, .8, .2]), .2)
    assert result["selected_count"] == 1
    assert result["precision_at_k"] == 1
    assert result["lift_at_k"] == 2.5
