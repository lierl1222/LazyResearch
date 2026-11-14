import numpy as np

from lazyresearch.science.agents import HypothesisScientist, ScientificReviewer, ResearchDirector, AlgorithmEngineer


def test_hypotheses_are_falsifiable_and_feedback_changes_route():
    profile = {"id": "dataset-profile", "features": ["a", "b"], "positive_rate": .2}
    hypotheses = HypothesisScientist().propose(profile)
    assert len({h.experiment_type for h in hypotheses}) >= 2
    assert all(h.falsification_condition and h.predicted_effect and h.observations for h in hypotheses)
    director = ResearchDirector()
    accepted = director.decide({"verdict": "accept", "experiment_type": "feature_interaction", "id": "r1"}, [], 0, 3)
    rejected = director.decide({"verdict": "reject", "experiment_type": "feature_interaction", "id": "r1"}, [], 0, 3)
    assert accepted["next_template"] != rejected["next_template"]
    assert accepted["evidence_ids"] == ["r1"]
    assert director.decide({"verdict": "reject", "id": "r2"}, [], 3, 3)["action"] == "stop"


def test_reviewer_rejects_worse_and_flags_inconsistent_protocol():
    y = [0, 1] * 50
    baseline = {"experiment_id": "b", "labels": y, "predictions": [0.1, .9] * 50,
                "spec": {"random_seed": 42, "validation_policy": "fixed_holdout", "metric": "average_precision"}}
    candidate = {"experiment_id": "e", "hypothesis_id": "h", "labels": y, "predictions": [.9, .1] * 50,
                 "spec": {**baseline["spec"], "experiment_type": "nonlinear_model"}}
    review = ScientificReviewer().review(candidate, baseline, 42, 50, 4)
    assert review["verdict"] == "reject"
    assert review["delta_interval"][1] < 0
    candidate["spec"]["random_seed"] = 43
    assert ScientificReviewer().review(candidate, baseline, 42, 50, 4)["verdict"] == "invalid"


def test_engineer_records_controlled_plan():
    h = HypothesisScientist().propose({"id": "p", "features": ["a", "b"]})[0]
    spec = AlgorithmEngineer().plan(h, "e1", ["a", "b"], 42, 10)
    assert spec.hypothesis_id == h.id
    assert spec.timeout_seconds == 10


def test_minimum_experiments_defers_patience_stop(tmp_path):
    from lazyresearch.science.graph import ScienceRunner
    from lazyresearch.science.schemas import TaskConfig
    cfg = TaskConfig.model_validate({"dataset": {"path": "unused", "target": "y"},
                                    "research": {"min_required_experiments": 5, "no_improvement_patience": 1}})
    runner = ScienceRunner(tmp_path, cfg)
    for h in HypothesisScientist().propose({"id": "p", "features": ["a", "b"]}):
        runner.registry.put("hypotheses", h.model_dump(), h.id)
    runner.registry.put("reviews", {"id": "review-e1", "verdict": "reject"}, "review-e1")
    runner.registry.put("experiments", {"experiment_id": "e1", "metrics": {}}, "e1")
    update = runner.decide({"iteration": 1, "stalled": 1, "completed_templates": ["feature_interaction"], "current_experiment": "e1"})
    assert "stop_reason" not in update
