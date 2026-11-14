"""Materialize the user-facing result from recorded evidence, including partial runs."""
import json
import uuid


def result_markdown(registry, report):
    if not report:
        return ""
    path = registry.root / "result.md"
    if path.exists():
        return path.read_text(encoding="utf8")
    states = {"reported":"已完成", "stopped":"已停止", "failed":"失败",
              "unsupported":"缺少可用工具", "inconclusive":"证据不足"}
    lines = ["# 研究结果", "", "运行状态：" + states.get(report["status"], report["status"]), ""]
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
    for e in registry.get("events") or []:
        if e.get("observation_id") and e.get("outcome"):
            evidence.setdefault(e["observation_id"], e["outcome"])
    if evidence:
        lines += ["## 实验记录", ""]
        for ref, observation in evidence.items():
            values = {k:v for k,v in observation.items() if k not in {
                "cpu_seconds","elapsed_seconds","wall_seconds","config_hash","run_id","experiment_id"}}
            lines += [f"- {ref} · " + json.dumps(values,ensure_ascii=False)]
    elif not benchmark.exists():
        lines += ["本次运行没有记录到可验证的实验结果。"]
    if report.get("summary"):
        lines += ["", "## 运行说明", "", report["summary"]]
    content = "\n".join(lines).rstrip() + "\n"
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(content, encoding="utf8")
    temporary.replace(path)
    return content
