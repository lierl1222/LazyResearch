from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lazyresearch.science.schemas import TaskConfig
from lazyresearch.science.data import prepare_dataset, generate_demo


def task(path: Path, **dataset):
    return TaskConfig.model_validate({"dataset": {"path": str(path), "target": "y", **dataset}})


def test_splits_reproducible_disjoint_and_forbidden_removed(tmp_path):
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=300, seed=42)
    cfg = task(path, forbidden_features=["duration"])
    first = prepare_dataset(cfg)
    second = prepare_dataset(cfg)
    assert first.split_indices == second.split_indices
    sets = [set(first.split_indices[k]) for k in ("train", "validation", "test")]
    assert not sets[0] & sets[1] and not sets[0] & sets[2] and not sets[1] & sets[2]
    assert len(set.union(*sets)) == 300
    assert "duration" not in first.X_train and "y" not in first.X_train
    assert first.profile["profile_scope"] == "train"
    assert first.profile["rows"] == 180


def test_target_copy_blocked_and_single_class_rejected(tmp_path):
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=120, seed=4)
    frame = pd.read_csv(path)
    frame["leaked_label"] = frame.y
    frame.to_csv(path, index=False)
    prepared = prepare_dataset(task(path))
    assert "leaked_label" not in prepared.X_train
    assert "leaked_label" in prepared.profile["blocked_features"]
    frame["y"] = 1
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="binary|二分类"):
        prepare_dataset(task(path))


def test_parquet_and_time_split(tmp_path):
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=300, seed=4)
    frame = pd.read_csv(path)
    frame["date"] = pd.date_range("2020-01-01", periods=300).astype(str)
    parquet = tmp_path / "demo.parquet"
    frame.to_parquet(parquet)
    cfg = task(parquet, format="parquet", time_column="date")
    cfg.validation.strategy = "temporal_holdout"
    result = prepare_dataset(cfg)
    assert max(result.split_indices["train"]) < min(result.split_indices["validation"])
    assert "date" not in result.X_train


def test_invalid_fractions_rejected(tmp_path):
    with pytest.raises(ValueError):
        TaskConfig.model_validate({"dataset": {"path": "x.csv", "target": "y"},
                                   "validation": {"train_fraction": .8}})


def test_preprocessing_statistics_are_training_only(tmp_path):
    from lazyresearch.science.experiments import ExperimentSpec, run_experiment
    path = tmp_path / "demo.csv"
    generate_demo(path, rows=120)
    data = prepare_dataset(task(path))
    expected = data.X_train["signal_a"].median()
    data.X_validation.loc[:, "signal_a"] = 100000
    _, model = run_experiment(ExperimentSpec(id="e", hypothesis_id="h"), data, .2)
    imputer = model.named_steps["preprocess"].named_transformers_["numeric"].named_steps["impute"]
    assert imputer.statistics_[0] == expected
