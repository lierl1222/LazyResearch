"""Reproduce a Favorita chronological benchmark and Kaggle-format predictions from a run."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from .forecast import Forecast, backtest, predict
from .research import append_report
from .science.registry import Registry


def benchmark(root, task=None):
    task = task or Registry(root).get("task")
    files = {f["name"]:f["id"] for f in task["files"]}
    params = dict(file_id=files["train.csv"], date="date", target="sales", groups=["store_nbr","family"], horizon=16)
    trials = []
    started = perf_counter()
    for weeks, promo in [(4,None),(8,None),(8,"onpromotion"),(12,"onpromotion")]:
        args = Forecast(**params, weeks=weeks, promotion=promo, fold=1)
        outcome = backtest(root, task, args)
        trial = dict(weeks=weeks,promotion=promo, **outcome)
        append_report(root,"benchmark_development",trial)
        trials.append(trial)
    best = min(trials,key=lambda t:t["candidate"])
    locked = Forecast(**params,weeks=best["weeks"],promotion=best["promotion"],fold=0)
    final = backtest(root,task,locked)
    test = pd.read_csv(root/"inputs"/files["test.csv"],parse_dates=["date"])
    train = pd.read_csv(root/"inputs"/files["train.csv"],parse_dates=["date"])
    cutoff = train.date.max()
    if test.date.min()<=cutoff:
        raise ValueError("Test dates overlap training data")
    history = train.loc[train.date>cutoff-pd.Timedelta(weeks=locked.weeks)].copy()
    _,pred,_ = predict(history,test,locked)
    output = test[["id"]].assign(sales=np.expm1(pred).clip(lower=0))
    template = pd.read_csv(root/"inputs"/files["sample_submission.csv"])
    if not output.id.equals(template.id) or not np.isfinite(output.sales).all():
        raise ValueError("Submission IDs or predictions invalid")
    output.to_csv(root/"submission.csv",index=False)
    result = dict(development=trials,selected=locked.model_dump(),holdout=final,
                  train_rows=len(train),series=train.groupby(locked.groups).ngroups,
                  prediction_rows=len(output),seconds=round(perf_counter()-started,2))
    (root/"benchmark.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    append_report(root,"benchmark_final",result)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("run_directory",type=Path)
    print(json.dumps(benchmark(parser.parse_args().run_directory),indent=2))
