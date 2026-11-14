"""Bounded CSV inspection and chronological evaluation on nonnegative daily panels."""
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from .models import Record


class InspectCSV(Record):
    file_id: str


def path_for(root, task, key):
    for item in task.get("files", []):
        if item["id"] == key and item["name"].lower().endswith(".csv"):
            return root / "inputs" / key
    raise ValueError("Select the file_id of an attached CSV")


def inspect_csv(root, task, args):
    path = path_for(root, task, args.file_id)
    sample = pd.read_csv(path, nrows=10000)
    return {"verdict": "observed", "file_id": args.file_id, "scope": "first 10000 rows at most",
            "rows_inspected": len(sample), "columns": list(sample.columns),
            "types": sample.dtypes.astype(str).to_dict(),
            "missing": sample.isna().sum().to_dict(), "duplicates_in_sample": int(sample.duplicated().sum())}


class Forecast(InspectCSV):
    date: str
    target: str
    groups: list[str] = Field(min_length=1, max_length=6)
    horizon: int = Field(default=16, ge=1, le=90)
    weeks: int = Field(default=4, ge=2, le=24)
    method: Literal["weekday_log_mean", "weekday_log_median"] = "weekday_log_mean"
    promotion: str | None = None
    fold: int = Field(default=0, ge=0, le=6)


def backtest(root, task, args):
    path = path_for(root, task, args.file_id)
    columns = [args.date, args.target, *args.groups] + ([args.promotion] if args.promotion else [])
    if len(set(columns)) != len(columns):
        raise ValueError("Date, target and grouping columns must be distinct")
    frame = pd.read_csv(path, usecols=columns)
    frame[args.date] = pd.to_datetime(frame[args.date], errors="raise").dt.normalize()
    frame[args.target] = pd.to_numeric(frame[args.target], errors="raise")
    keys = args.groups + [args.date]
    if frame[columns].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("Resolve missing values or duplicate series/date rows before scoring")
    if not np.isfinite(frame[args.target]).all() or (frame[args.target]<0).any():
        raise ValueError("RMSLE requires finite, nonnegative targets")
    end = frame[args.date].max() - pd.Timedelta(days=args.fold*args.horizon)
    cutoff = end - pd.Timedelta(days=args.horizon)
    history = frame.loc[frame[args.date].between(cutoff-pd.Timedelta(weeks=args.weeks)+pd.Timedelta(days=1),cutoff)].copy()
    holdout = frame.loc[frame[args.date].between(cutoff+pd.Timedelta(days=1), end)].copy()
    if history.empty or holdout.empty or holdout[args.date].nunique()!=args.horizon:
        raise ValueError("Insufficient history or incomplete validation horizon")
    return evaluate(history, holdout, args, cutoff, end)


def predict(history, holdout, args):
    for part in (history,holdout):
        part["_weekday"] = part[args.date].dt.weekday
    keys = args.groups + ["_weekday"]
    history["_value"] = np.log1p(history[args.target])
    history = history.sort_values(args.date)
    grouped = history.groupby(keys, observed=True)["_value"]
    stats = grouped.agg(baseline="last", candidate="mean" if args.method.endswith("mean") else "median")
    estimates = holdout.join(stats, on=keys)
    if args.promotion:
        # Learn a shrunk promotion effect from within-series, within-weekday residuals.
        x = np.log1p(pd.to_numeric(history[args.promotion], errors="raise").clip(lower=0))
        centered = x - x.groupby([history[k] for k in keys]).transform("mean")
        residual = history["_value"] - grouped.transform("mean")
        history["_cross"] = centered * residual
        history["_square"] = centered**2
        history["_promo"] = x
        moments = history.groupby(args.groups)[["_cross","_square"]].sum()
        slope = (moments["_cross"] / (moments["_square"] + 12)).clip(-1,1).rename("_slope")
        estimates = estimates.join(slope, on=args.groups).join(
            history.groupby(keys)["_promo"].mean(), on=keys)
        future = np.log1p(pd.to_numeric(estimates[args.promotion], errors="raise").clip(lower=0))
        estimates["candidate"] = (estimates["candidate"] + estimates["_slope"] *
                                  (future-estimates["_promo"])).clip(lower=0)
    fallback = estimates[args.groups].join(history.groupby(args.groups)["_value"].mean().rename("_fallback"),
                                         on=args.groups)["_fallback"].fillna(history["_value"].mean())
    return estimates["baseline"].fillna(fallback), estimates["candidate"].fillna(fallback), int(estimates["baseline"].isna().sum())


def evaluate(history, holdout, args, cutoff, end):
    base, model, missing = predict(history, holdout, args)
    truth = np.log1p(holdout[args.target])
    def score(prediction):
        return float(np.sqrt(((prediction-truth)**2).mean()))
    baseline, candidate = score(base), score(model)
    return {"verdict":"supported" if candidate<baseline else "refuted", "metric":"RMSLE",
            "baseline_method":"last available same weekday", "method":args.method,
            "train_end":str(cutoff.date()), "validation_end":str(end.date()), "validation_rows":len(truth),
            "fallback_rows":missing, "baseline":baseline, "candidate":candidate}
