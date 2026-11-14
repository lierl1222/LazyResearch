import math
import time
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, PolynomialFeatures, StandardScaler
from threadpoolctl import threadpool_limits

from ..models import Record
from .data import PreparedDataset


class ExperimentSpec(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    hypothesis_id: str
    experiment_type: Literal["baseline", "feature_interaction", "nonlinear_model", "class_imbalance", "segment_discovery"] = "baseline"
    data_features: list[str] = Field(default_factory=list)
    preprocessing: Literal["train_only_pipeline"] = "train_only_pipeline"
    model_name: Literal["dummy", "logistic", "random_forest"] = "logistic"
    model_params: dict[str, float | int | str] = Field(default_factory=dict)
    validation_policy: Literal["fixed_holdout"] = "fixed_holdout"
    metric: Literal["average_precision"] = "average_precision"
    random_seed: int = 42
    timeout_seconds: float = Field(default=90, gt=0, le=3600)

    @model_validator(mode="after")
    def controlled_parameters(self):
        permitted = {"dummy": {}, "logistic": {"C": (.001, 100)},
                     "random_forest": {"n_estimators": (10, 200), "max_depth": (1, 12), "min_samples_leaf": (2, 50)}}[self.model_name]
        for key, value in self.model_params.items():
            if key not in permitted or isinstance(value, (str, bool)):
                raise ValueError(f"Unsupported model parameter: {key}")
            low, high = permitted[key]
            if not low <= value <= high:
                raise ValueError(f"Parameter out of range: {key}")
            if key != "C" and int(value) != value:
                raise ValueError(f"Integer parameter required: {key}")
        if self.experiment_type == "nonlinear_model" and self.model_name != "random_forest":
            raise ValueError("nonlinear_model requires random_forest")
        if self.experiment_type in {"feature_interaction", "class_imbalance", "segment_discovery"} and self.model_name != "logistic":
            raise ValueError("Template requires logistic model")
        return self


def metrics(y: np.ndarray, probabilities: np.ndarray, top_fraction: float) -> dict:
    count = max(1, math.ceil(len(y) * top_fraction))
    selected = np.argsort(-probabilities, kind="stable")[:count]
    precision = float(y[selected].mean())
    prevalence = float(y.mean())
    return {"average_precision": float(average_precision_score(y, probabilities)),
            "roc_auc": float(roc_auc_score(y, probabilities)) if np.unique(y).size == 2 else None,
            "f1": float(f1_score(y, probabilities >= .5, zero_division=0)),
            "precision_at_k": precision, "lift_at_k": precision / prevalence if prevalence else None,
            "selected_count": count, "positive_rate": prevalence, "sample_count": len(y)}


def build_pipeline(spec: ExperimentSpec, data: PreparedDataset) -> Pipeline:
    features = spec.data_features or list(data.X_train.columns)
    if len(set(features)) != len(features) or not set(features) <= set(data.X_train.columns):
        raise ValueError("Experiment features must be unique permitted dataset features")
    numeric = [c for c in features if data.X_train[c].dtype.kind in "iufb"]
    categorical = [c for c in features if c not in numeric]
    numeric_steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if spec.experiment_type == "feature_interaction":
        if len(numeric) < 2:
            raise ValueError("Interaction template requires two numeric features")
        # Bound quadratic feature growth; explicit subset is retained in model/manifest.
        if len(numeric) > 12:
            raise ValueError("Interaction template permits at most 12 numeric features")
        numeric_steps.append(("interaction", PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)))
    numeric_steps.append(("scale", StandardScaler()))
    preprocessing = ColumnTransformer([
        ("numeric", Pipeline(numeric_steps), numeric),
        ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
                                   ("encode", OneHotEncoder(handle_unknown="ignore", max_categories=32, sparse_output=False))]), categorical),
    ])
    params = spec.model_params.copy()
    if spec.model_name == "dummy":
        model = DummyClassifier(strategy="prior")
    elif spec.model_name == "logistic":
        model = LogisticRegression(C=params.get("C", 1), max_iter=400, random_state=spec.random_seed,
                                   class_weight="balanced" if spec.experiment_type == "class_imbalance" else None)
    else:
        model = RandomForestClassifier(n_estimators=int(params.get("n_estimators", 60)),
                                       max_depth=int(params.get("max_depth", 5)),
                                       min_samples_leaf=int(params.get("min_samples_leaf", 4)),
                                       random_state=spec.random_seed, n_jobs=1)
    return Pipeline([("preprocess", preprocessing), ("model", model)])


def run_experiment(spec: ExperimentSpec, data: PreparedDataset, top_fraction: float) -> tuple[dict, Pipeline]:
    started, cpu = time.perf_counter(), time.process_time()
    pipeline = build_pipeline(spec, data)
    with threadpool_limits(limits=1):
        pipeline.fit(data.X_train, data.y_train)
        predictions = pipeline.predict_proba(data.X_validation)[:, 1]
    result = {"experiment_id": spec.id, "hypothesis_id": spec.hypothesis_id,
              "spec": spec.model_dump(), "comparison_scope": "validation",
              "metrics": metrics(data.y_validation, predictions, top_fraction),
              "predictions": predictions.tolist(), "labels": data.y_validation.tolist()}
    if spec.experiment_type == "segment_discovery":
        # Select a simple high-response rule using training labels only; validate unchanged.
        rules = []
        for column in data.X_train.select_dtypes(include="number"):
            threshold = float(data.X_train[column].median())
            for direction in ("above", "below"):
                mask = data.X_train[column] >= threshold if direction == "above" else data.X_train[column] < threshold
                if mask.sum() >= max(20, len(mask) // 10):
                    rules.append((float(data.y_train[mask].mean()), column, threshold, direction, int(mask.sum())))
        if rules:
            rate, column, threshold, direction, train_count = max(rules)
            mask = data.X_validation[column] >= threshold if direction == "above" else data.X_validation[column] < threshold
            n = int(mask.sum())
            result["segment"] = {"feature": column, "threshold": threshold, "direction": direction,
                                 "train_count": train_count, "train_response_rate": rate,
                                 "validation_count": n, "validation_coverage": n / len(mask),
                                 "validation_response_rate": float(data.y_validation[mask].mean()) if n else None,
                                 "validation_mask": mask.tolist(),
                                 "minimum_count": 20, "stable_sample_size": n >= 20}
        else:
            result["segment"] = {"reason": "No numeric rule with sufficient training samples"}
    result.update(elapsed_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu)
    return result, pipeline
