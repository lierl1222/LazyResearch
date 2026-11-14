"""Shorten model inputs while preserving evidence IDs and structured results."""


def compact_text(value, width):
    if isinstance(value, str):
        return value if len(value) <= width else value[:width] + "…"
    if isinstance(value, list):
        return [compact_text(item, width) for item in value[:12]]
    if isinstance(value, dict):
        return {key: compact_text(item, width) for key, item in value.items()
                if key not in {"config_hash", "data_hash", "cpu_seconds", "elapsed_seconds",
                               "wall_seconds", "run_id", "experiment_id", "baseline_ns", "candidate_ns"}}
    return value


def compact_research_context(context):
    compact = {key: compact_text(value, 180) for key, value in context.items()
               if key not in {"tools", "reports", "observations", "history", "prior_evidence"}}
    if "tools" in context:
        compact["tools"] = context["tools"] if "history" in context else {
            name: {"purpose": spec["purpose"]} for name, spec in context["tools"].items()
        }
    for key in ("observations", "prior_evidence"):
        if key in context:
            compact[key] = {ref: compact_text(value, 90) for ref, value in context[key].items()}
    if "history" in context:
        compact["history"] = compact_text(context["history"][-2:], 90)
    if "reports" in context:
        compact["reports"] = [
            compact_text({key: value for key, value in report.items() if key != "steps"}, 90)
            for report in context["reports"][-2:]
        ]
    return compact
