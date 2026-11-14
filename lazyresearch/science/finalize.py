import hashlib
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from .data import read_frame
from .experiments import metrics
from .registry import Registry
from .schemas import TaskConfig


def final_worker(root: Path, payload: dict):
    registry = Registry(root)
    config = TaskConfig.model_validate(payload["config"])
    locked = registry.get("locked_candidate")
    if not locked or locked["experiment_id"] != payload["candidate_id"]:
        raise ValueError("Candidate must be locked before final evaluation")
    with registry.transaction() as db:
        if registry.get_from(db, "test_gate", "current"):
            raise ValueError("Sealed test already consumed; final evaluation cannot be repeated")
        registry.put_into(db, "test_gate", "current", {"status": "consumed", "candidate_id": locked["experiment_id"]})
    dataset = registry.get("dataset")
    if hashlib.sha256(Path(config.dataset.path).read_bytes()).hexdigest() != dataset["sha256"]:
        raise ValueError("Dataset fingerprint mismatch")
    frame = read_frame(config).iloc[dataset["split_indices"]["test"]]
    features = registry.get("profile")["features"]
    X = frame[features].copy()
    numeric = X.select_dtypes(include="number").columns
    X[numeric] = X[numeric].replace([np.inf, -np.inf], np.nan)
    for column in X.columns.difference(numeric):
        X[column] = X[column].map(lambda item: str(item) if pd.notna(item) else np.nan).astype(object)
    y = (frame[config.dataset.target] == config.dataset.positive_label).astype(int).to_numpy()
    model = joblib.load(root / locked["model_artifact"])
    probabilities = model.predict_proba(X)[:, 1]
    rng = np.random.default_rng(config.validation.random_seed)
    positive, negative = np.where(y == 1)[0], np.where(y == 0)[0]
    values = []
    for _ in range(config.validation.bootstrap_samples):
        ix = np.concatenate([rng.choice(positive, len(positive)), rng.choice(negative, len(negative))])
        values.append(average_precision_score(y[ix], probabilities[ix]))
    pd.DataFrame({"row_index": dataset["split_indices"]["test"], "label": y, "probability": probabilities}).to_csv(root / "predictions_test.csv", index=False)
    shutil.copyfile(root / locked["model_artifact"], root / "best_model.joblib")
    return {"candidate_id": locked["experiment_id"], "comparison_scope": "sealed_test",
            "metrics": metrics(y, probabilities, config.objective.top_fraction),
            "average_precision_interval": np.quantile(values, [.025, .975]).tolist(),
            "predictions": probabilities.tolist(), "labels": y.tolist(),
            "limitations": ["Test score checks generalization of one locked candidate; it does not establish improvement over an unevaluated test baseline.",
                            "IID bootstrap may be optimistic for temporally dependent data."]}
