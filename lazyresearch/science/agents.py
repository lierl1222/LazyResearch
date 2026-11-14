"""Research roles share evidence contracts, not necessarily model instances."""
from typing import Literal

import numpy as np
from pydantic import Field
from sklearn.metrics import average_precision_score

from ..models import Record
from .data import prepare_dataset
from .experiments import ExperimentSpec


class HypothesisSpec(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    claim: str = Field(min_length=1, max_length=1000)
    observations: list[str] = Field(min_length=1, max_length=20)
    predicted_effect: str = Field(min_length=1, max_length=1000)
    falsification_condition: str = Field(min_length=1, max_length=1000)
    experiment_type: Literal["feature_interaction", "nonlinear_model", "class_imbalance", "segment_discovery"]
    priority: int = Field(default=1, ge=1, le=10)
    status: Literal["proposed", "testing", "supported", "rejected", "inconclusive"] = "proposed"


class DataScientist:
    prepare = staticmethod(prepare_dataset)


class HypothesisScientist:
    def propose(self, profile: dict) -> list[HypothesisSpec]:
        descriptions = [
            ("feature_interaction", "Pairwise feature interactions add predictive signal beyond additive logistic regression.",
             "Validation average precision increases relative to the same-split logistic baseline."),
            ("nonlinear_model", "A bounded tree ensemble captures nonlinear response patterns missed by a linear model.",
             "Validation average precision increases under identical split and features."),
            ("class_imbalance", "Class weighting improves response ranking despite imbalanced training prevalence.",
             "Ranking AP improves; changing a classification threshold alone cannot support this claim."),
            ("segment_discovery", "A training-selected numeric subgroup has stable above-average response on validation data.",
             "The same fixed rule covers at least 20 validation samples and exceeds overall response rate."),
        ]
        return [HypothesisSpec(id=f"h-{template}", claim=claim, observations=[profile["id"]],
                               predicted_effect=prediction,
                               falsification_condition=("Validation subgroup response does not exceed its complement, or uncertainty includes zero."
                                                       if template == "segment_discovery" else
                                                       "Paired validation AP difference is nonpositive or its adjusted uncertainty interval includes zero."),
                               experiment_type=template, priority=i + 1)
                for i, (template, claim, prediction) in enumerate(descriptions)]


class AlgorithmEngineer:
    def plan(self, hypothesis: HypothesisSpec, id: str, features: list[str], seed: int, timeout: float):
        return ExperimentSpec(id=id, hypothesis_id=hypothesis.id,
                              experiment_type=hypothesis.experiment_type, data_features=features,
                              model_name="random_forest" if hypothesis.experiment_type == "nonlinear_model" else "logistic",
                              random_seed=seed, timeout_seconds=timeout)


class ScientificReviewer:
    def review(self, candidate: dict, baseline: dict, seed: int, samples: int, comparisons: int) -> dict:
        result = {"id": f"review-{candidate['experiment_id']}", "experiment_id": candidate["experiment_id"],
                  "hypothesis_id": candidate.get("hypothesis_id"),
                  "experiment_type": candidate.get("spec", {}).get("experiment_type"),
                  "baseline_id": baseline.get("experiment_id"), "verdict": "invalid",
                  "method": "paired stratified bootstrap; Bonferroni-adjusted exploratory interval",
                  "limitations": ["Adaptive validation reuse creates selection bias; exploratory intervals are not confirmatory proof."]}
        if candidate.get("error") or baseline.get("error"):
            return {**result, "reason": "Experiment or baseline failed; no valid comparison."}
        if candidate.get("labels") != baseline.get("labels") or any(
            candidate["spec"].get(k) != baseline["spec"].get(k)
            for k in ("random_seed", "validation_policy", "metric")
        ):
            return {**result, "reason": "Inconsistent evaluation protocol or validation labels."}
        y = np.array(candidate["labels"])
        cp, bp = np.array(candidate["predictions"]), np.array(baseline["predictions"])
        if len(cp) != len(y) or len(bp) != len(y) or not np.isfinite(cp).all() or not np.isfinite(bp).all():
            return {**result, "reason": "Invalid prediction vector."}
        positive, negative = np.where(y == 1)[0], np.where(y == 0)[0]
        if not len(positive) or not len(negative):
            return {**result, "reason": "Both classes required for paired uncertainty."}
        rng = np.random.default_rng(seed)
        differences = []
        for _ in range(samples):
            ix = np.concatenate([rng.choice(positive, len(positive)), rng.choice(negative, len(negative))])
            differences.append(average_precision_score(y[ix], cp[ix]) - average_precision_score(y[ix], bp[ix]))
        alpha = .05 / max(1, comparisons)
        low, high = np.quantile(differences, [alpha / 2, 1 - alpha / 2]).tolist()
        delta = float(average_precision_score(y, cp) - average_precision_score(y, bp))
        verdict = "accept" if low > 0 else "reject" if delta <= 0 else "inconclusive"
        result.update(verdict=verdict, delta=delta, delta_interval=[low, high], bootstrap_samples=samples,
                      adjusted_alpha=alpha, reason="Support requires positive lower uncertainty bound; otherwise improvement is not established.")
        if candidate["spec"].get("experiment_type") == "segment_discovery":
            segment = candidate.get("segment", {})
            mask = np.array(segment.get("validation_mask", []), dtype=bool)
            result["segment"] = {k: v for k, v in segment.items() if k != "validation_mask"}
            if len(mask) != len(y) or mask.sum() < 20 or (~mask).sum() < 20:
                result.update(verdict="reject", reason="Subgroup or complement has fewer than 20 validation rows.")
            else:
                group, complement = y[mask], y[~mask]
                values = [rng.choice(group, len(group)).mean() - rng.choice(complement, len(complement)).mean() for _ in range(samples)]
                low, high = np.quantile(values, [alpha / 2, 1 - alpha / 2]).tolist()
                difference = float(group.mean() - complement.mean())
                result.update(verdict="accept" if low > 0 else "reject" if difference <= 0 else "inconclusive",
                              segment_delta=difference, segment_interval=[low, high],
                              reason="Fixed training-selected rule: compare subgroup vs complement response on validation, with adjusted bootstrap uncertainty.")
        return result


class ResearchDirector:
    def decide(self, review: dict, completed_templates: list[str], stalled: int, patience: int) -> dict:
        if stalled >= patience:
            return {"action": "stop", "reason": "no_improvement_patience", "evidence_ids": [review["id"]]}
        # Favor different competing explanations depending on the actual review.
        order = (["class_imbalance", "nonlinear_model", "segment_discovery", "feature_interaction"]
                 if review["verdict"] == "accept" else
                 ["nonlinear_model", "feature_interaction", "class_imbalance", "segment_discovery"])
        next_template = next((t for t in order if t not in completed_templates), None)
        if next_template is None:
            return {"action": "stop", "reason": "hypotheses_exhausted", "evidence_ids": [review["id"]]}
        return {"action": "continue" if next_template else "stop", "next_template": next_template,
                "reason": "Test a complementary explanation after supported evidence." if review["verdict"] == "accept" else
                          "Revise the route after unsupported or inconclusive evidence.",
                "evidence_ids": [review["id"]]}
