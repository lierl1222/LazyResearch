import hashlib
from pathlib import Path

from .experiments import ExperimentSpec
from .graph import ScienceRunner
from .registry import Registry
from .schemas import TaskConfig


def compare_final(original, replay):
    if original is None or replay is None:
        return {"matches": original is None and replay is None, "source_present": original is not None, "replay_present": replay is not None}
    fields = ["candidate_id", "metrics", "predictions", "labels", "error"]
    matches = {field: original.get(field) == replay.get(field) for field in fields}
    return {"matches": all(matches.values()), "field_matches": matches}


def reproduce(source: Path, destination: Path):
    if destination.exists():
        raise ValueError("Reproduction destination must not exist")
    original = Registry(source)
    config = TaskConfig.model_validate(original.get("task"))
    dataset = original.get("dataset")
    if not dataset or hashlib.sha256(Path(config.dataset.path).read_bytes()).hexdigest() != dataset["sha256"]:
        raise ValueError("Reproduction requires the exact original dataset")
    # Replay the recorded decisions/configs; never ask an LLM to rediscover them.
    config.llm.provider = "mock"
    runner = ScienceRunner(destination, config)
    with runner.registry.claim():
        state = runner.initialize({})
        if state.get("stop_reason"):
            runner.export(state)
            return state
        for h in original.list("hypotheses"):
            runner.registry.put("hypotheses", h, h["id"])
        for name, definition in original.list("science_tools"):
            runner.registry.put("science_tools", definition, name)
            runner.tools[name] = {"purpose": definition.get("purpose", ""), "custom": True,
                                  "source": definition.get("source", ""),
                                  "example": definition.get("example")}
        differences = []
        for previous in original.list("experiments"):
            spec = ExperimentSpec.model_validate(previous["spec"])
            baseline = runner.registry.get("experiments", "baseline-logistic") if spec.experiment_type != "baseline" else None
            result = runner._execute(spec, baseline)
            if result.get("review"):
                runner.registry.put("reviews", result["review"], result["review"]["id"])
            expected, actual = previous.get("metrics", {}), result.get("metrics", {})
            metric_deltas = {k: actual[k] - v for k, v in expected.items() if isinstance(v, (int, float)) and isinstance(actual.get(k), (int, float))}
            differences.append({"experiment_id": spec.id, "metric_deltas": metric_deltas,
                                "same_metrics": expected == actual, "same_error": previous.get("error") == result.get("error")})
        for decision in original.list("decisions"):
            runner.registry.put("decisions", {**decision, "source": "recorded_replay"}, decision["id"])
        locked = original.get("locked_candidate")
        if locked:
            runner.registry.put("locked_candidate", locked)
        # Reproduce final evaluation only if it was part of the original protocol.
        if original.get("test_evaluation") and not original.get("test_evaluation").get("error"):
            runner.final_evaluate({})
        else:
            runner.registry.put("test_skipped", {"reason": "not_evaluated_in_source_run"})
        final_comparison = compare_final(original.get("test_evaluation"), runner.registry.get("test_evaluation"))
        state = {"stop_reason": "replay_complete", "source_run": str(source.resolve()),
                 "comparison": differences, "final_test_comparison": final_comparison,
                 "metrics_match": all(d["same_metrics"] and d["same_error"] for d in differences) and final_comparison["matches"]}
        runner.registry.put("replay", state)
        runner.registry.put("final", state)
        runner.export(state)
        from .reporting import write_json
        write_json(destination, "reproduction_comparison.json", state)
        return state
