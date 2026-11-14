import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .schemas import TaskConfig


@dataclass
class PreparedDataset:
    X_train: pd.DataFrame
    X_validation: pd.DataFrame
    y_train: np.ndarray
    y_validation: np.ndarray
    split_indices: dict[str, list[int]]
    profile: dict
    dataset_hash: str


def generate_demo(path: Path, rows: int = 600, seed: int = 42) -> None:
    if rows < 60:
        raise ValueError("At least 60 demo rows required")
    rng = np.random.default_rng(seed)
    x1, x2, noise = rng.normal(size=(3, rows))
    category = rng.choice(["new", "returning", "unknown"], size=rows)
    logit = -1 + .6 * x1 + 2.5 * x1 * x2 + .5 * (category == "returning")
    response = rng.binomial(1, 1 / (1 + np.exp(-logit)))
    frame = pd.DataFrame({"signal_a": x1, "signal_b": x2, "noise": noise,
                          "customer_type": category, "duration": response * 100 + rng.normal(size=rows),
                          "y": response})
    frame.loc[rng.choice(rows, rows // 12, replace=False), "signal_a"] = np.nan
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def read_frame(config: TaskConfig) -> pd.DataFrame:
    path = Path(config.dataset.path)
    frame = pd.read_parquet(path) if config.dataset.format == "parquet" else pd.read_csv(path)
    if not frame.columns.is_unique:
        raise ValueError("Duplicate columns are not supported")
    if config.dataset.target not in frame:
        raise ValueError("Target column missing")
    if frame[config.dataset.target].isna().any() or frame[config.dataset.target].nunique() != 2:
        raise ValueError("A binary target with no missing values is required")
    if config.dataset.positive_label not in frame[config.dataset.target].unique():
        raise ValueError("positive_label is absent from target")
    return frame


def prepare_dataset(config: TaskConfig) -> PreparedDataset:
    frame = read_frame(config)
    target = config.dataset.target
    y = (frame[target] == config.dataset.positive_label).astype(int).to_numpy()
    indices = np.arange(len(frame))
    policy = config.validation
    if policy.strategy == "temporal_holdout":
        column = config.dataset.time_column
        if not column or column not in frame:
            raise ValueError("temporal_holdout requires time_column")
        dates = pd.to_datetime(frame[column], errors="raise")
        if dates.isna().any():
            raise ValueError("Missing timestamps")
        indices = np.argsort(dates.to_numpy(), kind="stable")
        a = int(len(frame) * policy.train_fraction)
        b = int(len(frame) * (policy.train_fraction + policy.val_fraction))
        train, val, test = indices[:a], indices[a:b], indices[b:]
        # Equal timestamp groups cannot straddle partition boundaries.
        if not len(train) or not len(val) or not len(test) or dates.iloc[train[-1]] >= dates.iloc[val[0]] or dates.iloc[val[-1]] >= dates.iloc[test[0]]:
            raise ValueError("Temporal boundaries must separate timestamp groups")
    else:
        train, rest = train_test_split(indices, train_size=policy.train_fraction,
                                       random_state=policy.random_seed, stratify=y)
        val, test = train_test_split(rest, train_size=policy.val_fraction / (policy.val_fraction + policy.test_fraction),
                                     random_state=policy.random_seed, stratify=y[rest])
    for name, split in [("train", train), ("validation", val), ("test", test)]:
        if len(split) < 4 or np.unique(y[split]).size != 2:
            raise ValueError(f"{name} split must contain both classes and at least 4 rows")

    blocked = set(config.dataset.forbidden_features) | {target}
    if config.dataset.time_column:
        blocked.add(config.dataset.time_column)
    training = frame.iloc[train]
    leakage = []
    # Detect deterministic target copies/recodings from training data only.
    # This cannot establish when a feature became available; domain denylist remains required.
    for column in frame.columns:
        if column in blocked:
            continue
        series = training[column]
        if series.nunique(dropna=False) == 2 and not series.isna().any():
            grouped = training.groupby(column, dropna=False)[target].nunique()
            if grouped.max() == 1:
                blocked.add(column)
                leakage.append(column)
    features = [c for c in frame.columns if c not in blocked]
    if not features:
        raise ValueError("No permitted features remain")
    X = frame[features].copy()
    numeric = X.select_dtypes(include="number").columns
    X[numeric] = X[numeric].replace([np.inf, -np.inf], np.nan)
    for column in X.columns.difference(numeric):
        X[column] = X[column].map(lambda item: str(item) if pd.notna(item) else np.nan).astype(object)
    profile = {
        "id": "dataset-profile", "profile_scope": "train", "rows": len(train),
        "total_rows": len(frame), "features": features,
        "dtypes": {c: str(X[c].dtype) for c in features},
        "missing": {c: int(X.iloc[train][c].isna().sum()) for c in features},
        "positive_rate": float(y[train].mean()),
        "blocked_features": sorted(blocked & set(frame.columns)),
        "detected_target_copies": leakage,
        "limitations": ["Domain knowledge is required to exclude future or target-derived information; automatic checks are incomplete."],
    }
    return PreparedDataset(X.iloc[train].copy(), X.iloc[val].copy(), y[train], y[val],
                           {"train": train.tolist(), "validation": val.tolist(), "test": test.tolist()},
                           profile, hashlib.sha256(Path(config.dataset.path).read_bytes()).hexdigest())
