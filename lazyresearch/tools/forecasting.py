from typing import Literal

from pydantic import Field

from ..forecast import Forecast, InspectCSV, backtest, inspect_csv
from ..models import Record


class ForecastParameters(Record):
    weeks: int = Field(ge=2, le=24)
    method: Literal["weekday_log_mean", "weekday_log_median"]
    use_promotion: bool


def favorita_spec(task, args, fold):
    train_id = next(file["id"] for file in task["files"] if file["name"] == "train.csv")
    return Forecast(file_id=train_id, date="date", target="sales", groups=["store_nbr", "family"],
                    horizon=16, weeks=args.weeks, method=args.method, fold=fold,
                    promotion="onpromotion" if args.use_promotion else None)


def favorita_candidate(root, task, args):
    spec = favorita_spec(task, args, fold=1)
    return {**backtest(root, task, spec), "scope": "favorita_development"}


def finalize_favorita(root, payload):
    from ..favorita_benchmark import finalize

    task = payload["task"]
    parameters = ForecastParameters.model_validate(payload["arguments"])
    spec = favorita_spec(task, parameters, fold=0)
    result = finalize(root, task, spec, payload["trials"])
    return {**result["holdout"], "scope": "favorita_holdout", "selected_weeks": spec.weeks,
            "prediction_rows": result["prediction_rows"], "artifact": "submission.csv"}
