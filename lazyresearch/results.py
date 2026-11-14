"""Materialize the user-facing result from recorded evidence, including partial runs."""
import uuid
import json

from .presentation import (STATUSES, chinese_text, display_references, explain_reason,
                           observation_title, present_events, present_outcome)


def result_markdown(registry, report, *, save=False):
    if not report:
        return ""
    lines = ["# 研究结果", "", "运行状态：" + STATUSES.get(report["status"], report["status"]), ""]
    benchmark = registry.root / "benchmark.json"
    if benchmark.exists():
        data = json.loads(benchmark.read_text(encoding="utf8"))
        score = data["holdout"]
        lines += [f"独立验证 {score['metric']}：模型 {score['candidate']:.5f}，基线 {score['baseline']:.5f}。"]
        if score["metric"] == "RMSLE" and score["baseline"] > 0:
            change = 100 * (score["candidate"] / score["baseline"] - 1)
            lines += [f"相对基线{'降低' if change < 0 else '增加'} {abs(change):.2f}%。"]
        lines += [f"训练截止 {score['train_end']}，验证截止 {score['validation_end']}，共 {score['validation_rows']:,} 条验证记录。",
                  f"预测文件 submission.csv 共 {data['prediction_rows']:,} 行。", ""]
    evidence = dict(report.get("evidence") or {})
    task = registry.get("task") or {}
    files = task.get("files", [])
    displays = {}
    for e in present_events(registry.get("events") or [], files):
        if e["stage"] == "validation" and e.get("observation_id") and e.get("outcome"):
            evidence.setdefault(e["observation_id"], e["outcome"])
            displays[e["observation_id"]] = e["display"]
    if evidence:
        lines += ["## 实验记录", ""]
        for ref, observation in evidence.items():
            display = displays.get(ref)
            if display:
                title, summary, fields = display["title"], display["summary"], display["fields"]
            else:
                title = observation_title(ref)
                summary, fields = present_outcome(observation, files)
            lines += [f"- {title} · {summary}"]
            lines += [f"  - {row['label']}：{row['value']}" for row in fields]
    elif not benchmark.exists():
        lines += ["本次运行没有记录到可验证的实验结果。"]
    if report.get("summary"):
        summary = report["summary"]
        if report["status"] in {"failed", "stopped"}:
            summary = explain_reason(summary)
        else:
            summary = chinese_text(summary, STATUSES[report["status"]] + "，详见上方实验记录。")
        summary = display_references(summary, {ref: display["title"] for ref, display in displays.items()})
        lines += ["", "## 运行说明", "", summary]
    content = "\n".join(lines).rstrip() + "\n"
    if save:
        path = registry.root / "result.md"
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(content, encoding="utf8")
        temporary.replace(path)
    return content
