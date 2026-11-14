"""Registered research capabilities. Only task-provided material reaches a worker."""
import random
from statistics import median
from time import perf_counter_ns
from typing import Literal

from pydantic import Field

from .models import Record


class Polynomial(Record):
    coefficients: list[int] = Field(min_length=1, max_length=12)


def sequence(root, task, args):
    values = task["sequence"]
    for n, observed in enumerate(values):
        predicted = sum(c * n**k for k, c in enumerate(args.coefficients))
        if predicted != observed:
            return {"verdict": "refuted", "n": n, "expected": observed, "actual": predicted}
    return {"verdict": "supported", "scope": "supplied indices only", "samples": len(values)}


class Benchmark(Record):
    method: Literal["list", "set", "sorted"]
    size: int = Field(default=2000, ge=10, le=10000)


def membership(root, task, args):
    from bisect import bisect_left
    rng = random.Random(task["seed"])
    data = rng.sample(range(args.size * 4), args.size)
    queries = rng.choices(range(args.size * 4), k=512)
    reference = [v in data for v in queries]

    def measure(method):
        start = perf_counter_ns()
        if method == "sorted":
            index = sorted(data)
            answers = []
            for v in queries:
                i = bisect_left(index, v)
                answers.append(i < len(index) and index[i] == v)
        else:
            index = set(data) if method == "set" else data
            answers = [v in index for v in queries]
        elapsed = perf_counter_ns() - start
        if answers != reference:
            raise ValueError("incorrect membership answers")
        return elapsed

    measure("list")
    measure(args.method)
    baseline, candidate = [], []
    for trial in range(7):
        order = (("list", baseline), (args.method, candidate))
        for method, samples in (order if trial % 2 == 0 else reversed(order)):
            samples.append(measure(method))
    ratio = median(baseline) / median(candidate)
    return {"verdict": "supported" if ratio >= task["target_speedup"] else "refuted",
            "speedup": ratio, "baseline_ns": baseline, "candidate_ns": candidate,
            "scope": "index construction and 512 lookups on the seeded workload"}


class Profile(Record):
    pass


def profile(root, task, args):
    from .science.agents import DataScientist
    from .science.schemas import TaskConfig
    data = DataScientist.prepare(TaskConfig.model_validate(task["tabular"]))
    return {"verdict": "observed", "profile": data.profile, "data_hash": data.dataset_hash}


class Tabular(Record):
    experiment_type: Literal["feature_interaction", "nonlinear_model", "class_imbalance", "segment_discovery"]
    features: list[str] = Field(default_factory=list)
    model_params: dict[str, int | float] = Field(default_factory=dict)


def tabular(root, task, args):
    from .science.agents import DataScientist, ScientificReviewer
    from .science.experiments import ExperimentSpec, run_experiment
    from .science.schemas import TaskConfig
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


# name -> (required material, description, argument schema, executor/validator)
TOOLS = {
    "table_profile": ("tabular", "Inspect training data and permitted features before designing a comparison.", Profile, profile),
    "sequence": ("sequence", "Test polynomial coefficients in ascending powers, indices start at zero.", Polynomial, sequence),
    "membership": ("cpu_benchmark", "Benchmark CPU membership implementations against a list on seeded inputs.", Benchmark, membership),
    "tabular": ("tabular", "Compare a tabular classifier strategy to logistic baseline on validation data.", Tabular, tabular),
}


def execute_tool(root, payload):
    _, _, schema, execute = TOOLS[payload["tool"]]
    return execute(root, payload["task"], schema.model_validate(payload["arguments"]))
