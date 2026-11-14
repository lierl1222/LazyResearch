from typing import Literal

from pydantic import Field

from ..models import Record


class Profile(Record):
    pass


def profile(root, task, args):
    from ..science.agents import DataScientist
    from ..science.schemas import TaskConfig
    data = DataScientist.prepare(TaskConfig.model_validate(task["tabular"]))
    return {"verdict": "observed", "profile": data.profile, "data_hash": data.dataset_hash}


class Tabular(Record):
    experiment_type: Literal["feature_interaction", "nonlinear_model", "class_imbalance", "segment_discovery"]
    features: list[str] = Field(default_factory=list)
    model_params: dict[str, int | float] = Field(default_factory=dict)


def tabular(root, task, args):
    from ..science.agents import DataScientist, ScientificReviewer
    from ..science.experiments import ExperimentSpec, run_experiment
    from ..science.schemas import TaskConfig
    config = TaskConfig.model_validate(task["tabular"])
    data = DataScientist.prepare(config)
    common = dict(random_seed=config.validation.random_seed, hypothesis_id="comparison")
    base = ExperimentSpec(id="baseline", **common)
    spec = ExperimentSpec(id="candidate", **common, data_features=args.features,
                          experiment_type=args.experiment_type, model_params=args.model_params,
                          model_name="random_forest" if args.experiment_type == "nonlinear_model" else "logistic")
    baseline, _ = run_experiment(base, data, config.objective.top_fraction)
    result, _ = run_experiment(spec, data, config.objective.top_fraction)
    review = ScientificReviewer().review(result, baseline, config.validation.random_seed,
                                         config.validation.bootstrap_samples, task["budget"]["max_experiments"])
    return {"verdict": {"accept": "supported", "reject": "refuted"}.get(review["verdict"], "inconclusive"),
            "scope": "exploratory validation split", "data_hash": data.dataset_hash,
            "metrics": result["metrics"], "baseline_metrics": baseline["metrics"], "review": review}


class UploadedTable(Tabular):
    file_id: str
    target: str
    positive_label: str | int | float = 1


def uploaded_table(root, task, args):
    if not any(f["id"] == args.file_id and f["name"].lower().endswith(".csv") for f in task.get("files", [])):
        raise ValueError("Select an attached CSV")
    from ..science.schemas import TaskConfig, DatasetConfig
    dataset = DatasetConfig(path=str(root / "inputs" / args.file_id), target=args.target, positive_label=args.positive_label)
    return tabular(root, {**task, "tabular": TaskConfig(dataset=dataset).model_dump()}, args)
