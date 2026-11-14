import random
from statistics import median
from time import perf_counter_ns
from typing import Literal

from pydantic import Field

from ..models import Record


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
