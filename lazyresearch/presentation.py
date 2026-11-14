"""Chinese labels and summaries for research events and reports."""
import re


TOOLS = {
    "favorita_benchmark": "Favorita 销量基准",
    "inspect_csv": "检查 CSV 数据",
    "forecast_backtest": "时间序列回测",
    "test_polynomial": "验证材料中的数列",
    "sequence": "验证给定数列",
    "membership": "CPU 成员查询基准",
    "benchmark_membership": "CPU 成员查询基准",
    "read_material": "读取研究材料",
    "uploaded_table": "CSV 分类实验",
    "tabular": "表格分类实验",
    "table_profile": "分析训练数据",
}
VERDICTS = {"observed": "已获得观测", "supported": "结果支持假设", "refuted": "结果未支持假设",
            "inconclusive": "证据不足", "invalid": "结果无效"}
STATUSES = {"reported": "已生成报告", "stopped": "已停止", "failed": "执行失败",
            "unsupported": "缺少可用工具", "inconclusive": "证据不足"}
REASONS = {
    "user_stop": "用户请求停止",
    "experiment_timeout": "单次实验达到时限",
    "wall_time_budget": "已达到总运行时限",
    "cpu_budget": "CPU 时间额度不足",
    "experiment_budget": "实验次数额度不足",
    "llm_call_budget": "模型调用次数额度不足",
    "cloud_request_budget": "云端请求额度不足",
    "token_budget": "Token 额度不足",
    "cost_budget_or_unknown_pricing": "费用额度不足或缺少计价配置",
    "No configured model endpoint": "没有可用的模型端点",
    "HTTPStatusError": "模型服务拒绝请求",
    "ConnectError": "无法连接模型服务",
    "ModelContextExceeded": "请求超过本地模型的上下文上限",
    "ReadTimeout": "模型服务响应超时",
    "TimeoutError": "模型请求超过时限",
    "ValidationError": "模型输出未通过格式校验",
    "ModelOutputTruncated": "模型输出达到长度上限，未能生成完整决策",
    "ValueError": "输入或工具配置无效",
    "FileNotFoundError": "找不到所需文件",
    "interrupted_execution_not_repeated": "实验中断，未取得完整结果",
}
METRICS = {"average_precision": "平均精确率（AP）", "roc_auc": "ROC-AUC", "f1": "F1",
           "precision_at_k": "前列样本精确率", "lift_at_k": "前列样本提升倍数"}


def explain_reason(reason):
    if reason in REASONS:
        return REASONS[reason]
    if re.search(r"[\u3400-\u9fff]", reason):
        return reason[:350]
    identifiers = ", ".join(dict.fromkeys(re.findall(r"'([\w.]+)'", reason)))[:150]
    if identifiers:
        return f"工具无法处理输入，请核对字段或参数（{identifiers}）。"
    if reason.startswith("worker_exit_"):
        return "实验进程异常退出，未取得结果。"
    if reason.startswith("ValueError:"):
        return "实验数据或参数未通过校验。"
    return "当前操作未能完成。"


def chinese_text(value, fallback):
    return value if re.search(r"[\u3400-\u9fff]", value or "") else fallback


def observation_title(reference, label="验证记录"):
    if reference == "favorita-final":
        return "Favorita 最终独立验证"
    match = re.fullmatch(r"worker-(\d+)-(\d+)", reference or "")
    if match:
        turn, step = (int(n) + 1 for n in match.groups())
        return f"第 {turn} 轮 · 第 {step} 次工具操作 · {label}"
    return label


def display_references(text, references):
    return re.sub(r"\bworker-\d+-\d+\b",
                  lambda match: references.get(match[0], observation_title(match[0])), text)


def present_outcome(outcome, files=()):
    fields = []

    def add(label, value):
        if value is not None and value != "":
            fields.append({"label": label, "value": str(value)})

    if outcome.get("error"):
        return "执行失败", [{"label": "原因", "value": explain_reason(outcome["error"])}]

    summary = VERDICTS.get(outcome.get("verdict"), "已取得结果")
    if outcome.get("match") is False:
        summary = "未找到匹配内容"
    if outcome.get("excerpt"):
        summary = "已读取材料片段"
        add("原文摘录", outcome["excerpt"])
    source = outcome.get("source") or outcome.get("file_id")
    names = {file["id"]: file["name"] for file in files}
    add("来源", "研究目标" if source == "task" else names.get(source))
    add("查找内容", outcome.get("query"))
    if "length" in outcome:
        add("材料长度", f'{outcome["length"]:,} 字符')
    if "n" in outcome and "actual" in outcome:
        add("首个不符下标", outcome["n"])
        add("给定数值", outcome.get("expected"))
        add("预测数值", outcome["actual"])
    if "samples" in outcome:
        add("已检查样本", outcome["samples"])
    if isinstance(outcome.get("speedup"), (int, float)):
        add("相对列表基线", f'{outcome["speedup"]:.2f} 倍')
    if isinstance(outcome.get("columns"), list):
        add("字段", "、".join(str(column) for column in outcome["columns"][:20]))
    for key, label in (("rows_inspected", "检查行数"), ("duplicates_in_sample", "样本重复行数"),
                       ("validation_rows", "验证行数"), ("train_end", "训练截止日期"),
                       ("validation_end", "验证截止日期"), ("prediction_rows", "预测行数"),
                       ("selected_weeks", "训练窗口（周）")):
        add(label, outcome.get(key))
    metric = outcome.get("metric")
    if metric and "candidate" in outcome and "baseline" in outcome:
        add(f"候选 {metric}", f'{outcome["candidate"]:.5f}')
        reference = "季节朴素基线" if outcome.get("scope") == "favorita_development" else "基线"
        add(f"{reference} {metric}", f'{outcome["baseline"]:.5f}')
        if metric == "RMSLE":
            if outcome.get("scope") == "favorita_development":
                add("验证范围", "开发折")
                if "previous_best_rmsle" in outcome:
                    add("此前最低 RMSLE", f'{outcome["previous_best_rmsle"]:.5f}')
                    summary = ("候选降低了同一开发折的最低 RMSLE，更新最优方案" if outcome["improved"]
                               else "候选未降低同一开发折的最低 RMSLE，保留原方案")
                else:
                    summary = "已取得首个开发折分数"
            else:
                summary = ("候选 RMSLE 低于季节朴素基线" if outcome["candidate"] < outcome["baseline"]
                           else "候选 RMSLE 未低于季节朴素基线")
    baseline = outcome.get("baseline_metrics", {})
    for key, value in outcome.get("metrics", {}).items():
        if key in METRICS and isinstance(value, (int, float)):
            reference = baseline.get(key)
            detail = f"{value:.5f}" + (f"（基线 {reference:.5f}）" if isinstance(reference, (int, float)) else "")
            add(METRICS[key], detail)
    if outcome.get("scope") == "exploratory validation split":
        add("验证范围", "探索性验证集")
    if outcome.get("scope") == "supplied indices only":
        add("验证范围", "限已提供的下标")
    interval = outcome.get("review", {}).get("delta_interval")
    if interval:
        add("AP 差值区间", f"{interval[0]:.5f} 至 {interval[1]:.5f}")
    profile = outcome.get("profile", {})
    if profile:
        add("训练集行数", profile.get("rows"))
        add("可用特征", "、".join(profile.get("features", [])[:20]))
    for field in outcome.get("display_fields", []):
        if isinstance(field, dict) and isinstance(field.get("label"), str):
            add(field["label"], field.get("value"))
    add("产物", outcome.get("artifact"))
    if isinstance(outcome.get("wall_seconds"), (int, float)):
        add("耗时", f'{outcome["wall_seconds"]:.2f} 秒')
    return summary, fields


def present_arguments(arguments, files):
    labels = {"date": "日期列", "target": "目标列", "groups": "分组列",
              "horizon": "预测天数", "weeks": "训练窗口（周）", "promotion": "促销列",
              "fold": "时间折", "method": "方法", "use_promotion": "使用促销",
              "query": "查找内容", "coefficients": "多项式系数",
              "experiment_type": "实验类型", "features": "实验特征", "size": "输入规模"}
    values = {"weekday_log_mean": "按工作日计算对数均值", "weekday_log_median": "按工作日计算对数中位数",
              "feature_interaction": "特征交互", "nonlinear_model": "非线性模型",
              "class_imbalance": "类别不平衡处理", "segment_discovery": "子群体发现",
              "list": "列表查找", "set": "集合查找", "sorted": "排序后二分查找"}
    fields = []
    file_name = next((f["name"] for f in files if f["id"] == arguments.get("file_id")), None)
    if file_name:
        fields.append({"label": "数据文件", "value": file_name})
    for name, label in labels.items():
        value = arguments.get(name)
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            value = "、".join(map(str, value))
        if isinstance(value, bool):
            value = "是" if value else "否"
        value = values.get(value, value)
        fields.append({"label": label, "value": str(value)})
    return fields


def present_events(events, files=()):
    results = []
    active_tools = {}
    references = {}
    for event in events:
        if event["stage"] == "execution":
            label = event.get("tool_label") or TOOLS.get(event.get("summary"), "工具执行")
            if event.get("observation_id"):
                active_tools[event["observation_id"]] = label
            active_tools[event.get("round")] = label
        if event["stage"] == "validation" and event.get("observation_id"):
            ref = event["observation_id"]
            label = event.get("tool_label") or active_tools.get(ref) or active_tools.get(event.get("round"), "验证记录")
            references[ref] = observation_title(ref, label)
    for event in events:
        stage, turn = event["stage"], event.get("round")
        title = f"第 {turn} 轮" if turn is not None else "研究进度"
        summary = event.get("summary", "")
        fields = []
        decision = event.get("decision") or {}
        if stage == "plan" and decision:
            if decision.get("action") == "delegate":
                title += " · 规划下一步"
                summary = chinese_text(summary, "已委派下一项可验证任务，具体操作见后续实验记录。")
                complexity = "复杂推理" if decision.get("reasoning_level") == "complex" else "常规推理"
                fields.append({"label": "推理类型", "value": complexity})
            else:
                title += " · 整理研究结论"
                summary = chinese_text(summary, "已请求整理结论，依据见验证记录。")
            cited = [references[ref] for ref in decision.get("evidence", []) if ref in references]
            if cited:
                fields.append({"label": "依据", "value": "；".join(cited)})
        if stage == "hypothesis":
            summary = chinese_text(summary, "提出待验证假设并选择工具。")
            if event.get("tool_label"):
                fields.append({"label": "所选工具", "value": event["tool_label"]})
            prediction = chinese_text(event.get("prediction"), "")
            if prediction:
                fields.append({"label": "预期结果", "value": prediction})
        if stage == "execution":
            summary = event.get("tool_label") or TOOLS.get(summary, "运行研究工具")
            fields = present_arguments(event.get("arguments", {}), files)
        if stage == "validation" and "outcome" in event:
            title = references.get(event.get("observation_id"), title + " · 验证")
            summary, fields = present_outcome(event["outcome"], files)
        summary = display_references(summary, references)
        results.append({**event, "display": {"title": title, "summary": summary, "fields": fields}})
    return results


def progress_entry(stage, details, files=(), display=None):
    headings = {"queued": "已排队", "running": "研究开始", "task": "研究任务",
                "plan": "研究规划", "hypothesis": "提出假设", "execution": "实验或分析",
                "validation": "验证", "revision": "修正", "conclusion": "研究结论",
                "finished": "研究结束", "chat": "已更新对话记忆",
                "benchmark_development": "Favorita 开发折比较", "benchmark_final": "Favorita 独立验证"}
    if stage in {"model", "model_request"}:
        role = "云端" if details.get("role") == "cloud" or details.get("summary", "").startswith("cloud") else "本地"
        message = f"{role}模型 {details.get('model', '')}".strip()
        if details.get("reason"):
            message += " · " + explain_reason(details["reason"])
        return ("请求模型" if stage == "model_request" else "模型响应"), [message]
    if stage in {"benchmark_development", "benchmark_final"}:
        observation = details if stage == "benchmark_development" else details["holdout"]
        summary, fields = present_outcome(observation, files)
        return headings[stage], [summary, *(f"- {row['label']}：{row['value']}" for row in fields)]
    if display is None:
        display = present_events([{"stage": stage, **details}], files)[0]["display"]
    heading = headings.get(stage, "研究进度")
    if details.get("round"):
        heading += " · " + display["title"]
    summary = display["summary"] or details.get("goal", "")
    if details.get("status") in {"stopped", "failed"} and summary:
        summary = explain_reason(summary)
    elif details.get("status") in STATUSES and stage in {"conclusion", "finished"}:
        summary = chinese_text(summary, STATUSES[details["status"]] + "，详见验证记录。")
    return heading, [summary, *(f"- {row['label']}：{row['value']}" for row in display["fields"])]
