import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import yaml


def write_json(root, name, value):
    path = root / name
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def export_report(registry, config, budget, state):
    root = registry.root
    experiments = registry.list("experiments")
    hypotheses, reviews, decisions = (registry.list(k) for k in ("hypotheses", "reviews", "decisions"))
    final, locked = registry.get("test_evaluation"), registry.get("locked_candidate")
    snapshot = budget.snapshot()
    fallback = registry.get("fallback")
    mode = (fallback.get("mode", "mock_fallback") if fallback
            else "api" if config.llm.provider == "configured_api" else "mock")
    if registry.get("replay"):
        mode = "recorded_replay"
    versions = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn", "scipy", "langgraph", "pyarrow")}
    source_files = sorted(Path(__file__).parent.glob("*.py"))
    source_hash = hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in source_files)).hexdigest()
    manifest = {"run_id": root.name, "mode": mode, "stop_reason": state.get("stop_reason"),
                "random_seed": config.validation.random_seed, "dataset": registry.get("dataset"),
                "config_sha256": hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
                "environment": {"python": platform.python_version(), "platform": platform.platform(), "packages": versions},
                "science_source_sha256": source_hash,
                "locked_candidate": locked, "test_evaluations": int(registry.get("test_gate") is not None),
                "test_status": "completed" if final and not final.get("error") else "failed" if final else "not_evaluated",
                "reproduce_command": f'python -m lazyresearch.science reproduce --run-dir "{root.resolve()}"',
                "artifacts": ["config.resolved.yaml", "dataset_profile.json", "baseline_metrics.json", "hypotheses.jsonl", "experiments.jsonl", "reviews.jsonl", "analyses.jsonl", "science_tools.jsonl", "decision_trace.jsonl", "budget.json", "report.md"]}
    for kind, name in [("hypotheses", "hypotheses.jsonl"), ("experiments", "experiments.jsonl"), ("reviews", "reviews.jsonl"),
                       ("analyses", "analyses.jsonl"), ("science_tools", "science_tools.jsonl"),
                       ("decisions", "decision_trace.jsonl"), ("model_calls", "model_calls.jsonl")]:
        registry.export(kind, name)
    baseline_control = {"id": "baseline-control", "claim": "Logistic regression establishes a same-split predictive reference against the constant prior.",
                        "observations": ["dataset-profile"], "predicted_effect": "Measured validation AP establishes a control, not an assumed improvement.",
                        "falsification_condition": "Observed metrics do not establish discrimination beyond the constant prior.",
                        "experiment_type": "baseline", "status": "control"}
    with (root / "hypotheses.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(baseline_control) + "\n")
    for name, value in [("run_manifest.json", manifest), ("budget.json", snapshot), ("dataset_profile.json", registry.get("profile")),
                        ("baseline_metrics.json", [e for e in experiments if e["spec"]["experiment_type"] == "baseline"]),
                        ("test_metrics.json", final)]:
        write_json(root, name, value)
    (root / "config.resolved.yaml").write_text(yaml.safe_dump(config.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    dependencies = sorted(f"{distribution.metadata['Name']}=={distribution.version}" for distribution in importlib.metadata.distributions() if distribution.metadata.get("Name"))
    (root / "requirements.freeze.txt").write_text("\n".join(dependencies) + "\n", encoding="utf-8")
    lines = ["# LazyResearch 研究报告", "", f"运行：{root.name}；模式：{mode}；停止原因：{state.get('stop_reason')}",
             "", "## 任务与数据", config.objective.description,
             f"目标字段：{config.dataset.target}；排序覆盖比例：{config.objective.top_fraction}；主指标：Average Precision（AP，非梯形 PR 曲线面积）。",
             "画像仅来自训练数据；预处理只在训练集拟合；验证集用于探索；最终测试在方案冻结后至多评估一次。",
             "```json", json.dumps(registry.get("profile"), ensure_ascii=False, indent=2), "```",
             f"划分策略：{config.validation.strategy}；种子：{config.validation.random_seed}；索引与数据 SHA-256 见 run_manifest.json。",
             "", "## 假设与证据"]
    for h in hypotheses:
        lines.extend([f"- {h['id']} [{h['status']}]：{h['claim']}", f"  证据：{', '.join(h['observations'])}；预期：{h['predicted_effect']}；证伪：{h['falsification_condition']}"])
    lines.extend(["", "## 全部实验（包含失败）", "| 实验 | 假设 | 验证 AP | 结果 |", "|---|---|---|---|"])
    for e in experiments:
        lines.append(f"| {e['experiment_id']} | {e['hypothesis_id']} | {e.get('metrics', {}).get('average_precision', '未得到')} | {e.get('error', '完成')} |")
    lines.extend(["", "所有指标及预测来自 experiments.jsonl；配置哈希和耗时见每条原始记录。", "", "## 审查与决策"])
    for r in reviews:
        lines.append(f"- {r['id']} → {r['verdict']}：{r['reason']}；差值区间 {r.get('delta_interval', '不适用')}。")
    for d in decisions:
        source = {"local": "本地模型", "cloud": "云端模型", "deterministic_fallback": "确定性回退", "recorded_replay": "复现重放"}.get(d.get("source"), d.get("source", "确定性回退"))
        lines.append(f"- {d['id']}：{d['action']}；{d['reason']}；依据 {d['evidence_ids']}；决策来源 {source}。")
    analyses = registry.list("analyses")
    if analyses:
        lines.extend(["", "## 实验分析（模型解读）"])
        for a in analyses:
            lines.extend([f"- {a['id']}：{a['summary']}",
                          f"  含义：{a['implications']}",
                          *((f"  异常：{a['anomalies']}",) if a.get("anomalies") else ()),
                          *((f"  建议下一步：{a['suggested_next']}",) if a.get("suggested_next") else ())])
    custom_tools = registry.list("science_tools")
    if custom_tools:
        lines.extend(["", "## 自定义工具（JS 沙箱注册）"])
        for t in custom_tools:
            lines.append(f"- {t['name']}：{t['purpose']}")
    lines.extend(["", "## 冻结方案与最终测试", f"验证集选择：{locked['experiment_id'] if locked else '无有效候选'}。"])
    if final and not final.get("error"):
        lines.extend(["最终测试真实指标（来源 test_metrics.json / predictions_test.csv）：", "```json",
                      json.dumps(final["metrics"], ensure_ascii=False, indent=2), "```",
                      f"测试 AP Bootstrap 95% 区间：{final['average_precision_interval']}。"])
    else:
        lines.append(f"最终测试未完成：{final.get('error') if final else registry.get('test_skipped') or '无可评估模型'}。")
    lines.extend(["", "## 结论与局限", "未证实改善的假设必须保留；验证集最优不等于已证实泛化提升。",
                  "探索性多重比较使用调整区间，仍受自适应模型选择偏差影响。小样本及时间相关数据的 IID Bootstrap 可能过于乐观。",
                  "自动泄漏检查并不完整，用户必须排除决策后字段与目标衍生字段；本研究仅预测响应倾向，不推断因果增量。",
                  "Mock 模式只验证编排与真实工具链，不代表真实 LLM 科研能力。" if mode != "api" else "模型只提供研究决策，指标全部由确定性工具计算。",
                  "", "## 资源使用", f"输入 Token：{snapshot['input_tokens']}；输出 Token：{snapshot['output_tokens']}；调用：{snapshot['llm_calls']}；未知用量调用：{snapshot['unknown_usage_calls']}。",
                  f"API 美元费用：{snapshot['api_cost_usd'] if snapshot['api_cost_usd'] is not None else '未知，未配置可靠价格'}；实验次数（含最终评估）：{snapshot['experiment_count']}。",
                  f"科学计算 CPU 秒（含不明操作保守预留）：{snapshot['cpu_seconds']}；墙钟秒：{snapshot['wall_seconds']}。预算逐操作记录见 budget.json。",
                  "", "## 复现", "```powershell", manifest["reproduce_command"], "```",
                  "环境版本、配置、划分与数据指纹见 manifest。复现重放已记录实验配置，不重新调用收费模型。",
                  "", "## 后续建议", "对未证实假设收集独立数据后再验证；预算不足时明确保留未评估结论，不将失败改写为提升。"])
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
