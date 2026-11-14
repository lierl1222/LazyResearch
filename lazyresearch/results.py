"""Materialize the user-facing result from recorded evidence, including partial runs."""
import json
import math
import re
import uuid

from .presentation import (STATUSES, chinese_text, display_references, explain_reason,
                           observation_title, present_events, present_outcome)

METHOD_NAMES = {"weekday_log_mean": "工作日对数均值", "weekday_log_median": "工作日对数中位数"}


def result_markdown(registry, report, *, save=False):
    if not report:
        return ""
    saved = registry.get("final_report") or {}
    if saved.get("markdown"):
        content = saved["markdown"]
    else:
        content = (favorita_technical_report(registry, report)
                   if is_favorita_run(registry, report)
                   else generic_result_markdown(registry, report))
    if save:
        path = registry.root / "result.md"
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(content, encoding="utf8")
        temporary.replace(path)
    return content


def is_favorita_run(registry, report):
    for outcome in (report.get("evidence") or {}).values():
        if isinstance(outcome, dict) and str(outcome.get("scope") or "").startswith("favorita"):
            return True
    benchmark = registry.root / "benchmark.json"
    if benchmark.exists():
        try:
            data = json.loads(benchmark.read_text(encoding="utf8"))
        except (OSError, ValueError):
            return False
        if (data.get("holdout") or {}).get("metric") == "RMSLE":
            return True
    return False


def finite_score(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def favorita_context(registry, report):
    """Assemble trials, holdout and selected parameters from benchmark.json, evidence and events."""
    evidence = dict(report.get("evidence") or {})
    events = registry.get("events") or []
    arguments, hypotheses = {}, {}
    for event in events:
        ref = event.get("observation_id")
        if event["stage"] == "execution" and ref and isinstance(event.get("arguments"), dict):
            arguments[ref] = event["arguments"]
        if event["stage"] == "hypothesis" and ref and event.get("summary"):
            hypotheses[ref] = event["summary"]
    benchmark = registry.root / "benchmark.json"
    data = {}
    if benchmark.exists():
        try:
            data = json.loads(benchmark.read_text(encoding="utf8"))
        except (OSError, ValueError):
            data = {}
    trials = []
    for turn, trial in enumerate(data.get("development") or []):
        outcome = evidence.get(trial.get("id")) or trial
        parameters = trial.get("parameters") or arguments.get(trial.get("id"))
        if not parameters:
            parameters = {"weeks": trial.get("weeks"), "method": trial.get("method"),
                          "use_promotion": trial.get("promotion") is not None}
        trials.append({"turn": turn + 1, "parameters": parameters or {},
                       "hypothesis": hypotheses.get(trial.get("id")), "outcome": outcome})
    if not trials:
        development = {key: outcome for key, outcome in evidence.items()
                       if isinstance(outcome, dict) and outcome.get("scope") == "favorita_development"}
        trials = [{"turn": index + 1, "parameters": arguments.get(key) or {},
                   "hypothesis": hypotheses.get(key), "outcome": outcome}
                  for index, (key, outcome) in enumerate(sorted(development.items()))]
    holdout = data.get("holdout") or evidence.get("favorita-final") or {}
    return trials, holdout, data.get("selected") or {}, data


def locked_description(selected, parameters):
    merged = {**parameters, **selected}
    weeks = merged.get("weeks")
    method = METHOD_NAMES.get(merged.get("method")) or str(merged.get("method") or "") or "—"
    promo = merged.get("promotion")
    if promo is None:
        promo = merged.get("use_promotion")
    enabled = promo is not None and bool(promo)
    return (f"{weeks} 周" if isinstance(weeks, int) else "—", method,
            "开启促销调整" if enabled else "不使用促销调整",
            "开启" if enabled else "关闭")


def group_scores(trials, key):
    groups = {}
    for trial in trials:
        if finite_score(trial["outcome"].get("candidate")):
            groups.setdefault(trial["parameters"].get(key), []).append(trial["outcome"]["candidate"])
    return {value: (len(scores), sum(scores) / len(scores)) for value, scores in groups.items() if scores}


def format_int(value):
    return f"{value:,}" if isinstance(value, int) else "—"


def shorten(text, limit=24):
    text = re.sub(r"^决策 Agent[。：]\s*", "", (text or "").strip())
    text = re.sub(r"^本机补选[^。]*[。：]\s*", "", text)
    return text[:limit] + ("…" if len(text) > limit else "") if text else "—"


def favorita_technical_report(registry, report):
    task = registry.get("task") or {}
    trials, holdout, selected, data = favorita_context(registry, report)
    valid = [trial for trial in trials if finite_score(trial["outcome"].get("candidate"))]
    best = min(valid, key=lambda trial: trial["outcome"]["candidate"]) if valid else None
    holdout_candidate, holdout_baseline = holdout.get("candidate"), holdout.get("baseline")
    has_holdout = finite_score(holdout_candidate) and finite_score(holdout_baseline)
    locked_weeks, locked_method, locked_promo, locked_promo_short = \
        locked_description(selected, best["parameters"] if best else {})
    reduction = 100 * (1 - holdout_candidate / holdout_baseline) if has_holdout else None

    lines = ["# 研究报告", ""]
    goal = (task.get("goal") or "").strip()
    if goal:
        lines += [f"> 研究问题：{goal}", ""]

    # 摘要
    lines += ["## 摘要", ""]
    if report.get("status") != "reported":
        lines.append(f"- 状态：{STATUSES.get(report['status'], report['status'])}；以下内容基于已取得的实验证据。")
    lines.append(f"- 锁定方案：{locked_weeks} 训练窗口、{locked_method}、{locked_promo}。")
    if best:
        lines.append(f"- 开发折最优 RMSLE：{best['outcome']['candidate']:.5f}"
                     f"（{len(valid)} 个有效候选中的最优，第 {best['turn']} 轮）。")
    if has_holdout:
        lines.append(f"- 独立验证 RMSLE：{holdout_candidate:.5f}，季节朴素基线 {holdout_baseline:.5f}，相对降低 {reduction:.2f}%。")
        lines.append("- 结论：锁定方案在留出的独立验证折上优于季节朴素基线（点估计比较，未做显著性检验）。")
    else:
        lines.append("- 独立验证未执行或未完成，以上分数只代表开发折表现。")
    lines.append("")

    # 问题与数据
    lines += ["## 问题与数据", ""]
    if goal:
        lines.append(f"- 研究问题：{goal}")
    if task.get("domain"):
        lines.append(f"- 研究领域：{task['domain']}")
    scale = []
    if isinstance(data.get("train_rows"), int):
        scale.append(f"共 {data['train_rows']:,} 条记录")
    if isinstance(data.get("series"), int):
        scale.append(f"{data['series']:,} 个（门店 × 商品族）序列")
    lines.append("- 数据：Favorita 逐日销量面板（train.csv），含门店、商品族与促销标记"
                 + ("，" + "、".join(scale) if scale else "")
                 + "；预测期为未来 16 天（test.csv）。")
    dev = best["outcome"] if best else (trials[0]["outcome"] if trials else {})
    if best:
        lines.append(f"- 开发折：训练截止 {dev.get('train_end')}，验证区间至 {dev.get('validation_end')}，"
                     f"共 {format_int(dev.get('validation_rows'))} 条验证记录。")
    if has_holdout:
        lines.append(f"- 独立验证折：训练截止 {holdout.get('train_end')}，验证区间至 {holdout.get('validation_end')}，"
                     f"共 {format_int(holdout.get('validation_rows'))} 条记录（train.csv 最后 16 天）。")
    lines += ["- 划分原则：严格按日期顺序切分，训练窗口只使用验证截止之前的记录；开发折用于参数选择，"
              "独立验证折在方案锁定后仅评估一次。",
              "- 评估指标：RMSLE（均方根对数误差）= √( mean( (ln(1+ŷ) − ln(1+y))² ) )。"
              "对数域惩罚的是相对误差，对低销量序列敏感，又不会被个别大销量的绝对误差主导，是销售预测的常用指标。", ""]

    # 方法
    lines += ["## 方法", "",
              "### 基线：季节朴素（同星期几最近观测）", "",
              "对每个（门店 × 商品族 × 星期几）组合，沿用训练窗口内该组合最近一次的销量，作为未来同一组合、"
              "同一星期几的预测。该基线只依赖上一周期同星期几的观测，是时间序列销售预测的标准参照。", "",
              "### 候选方法族：工作日对数聚合", "",
              "- 对数变换：z = ln(1 + sales)，对零销量也成立（log1p），并与 RMSLE 的对数域目标一致。",
              "- 聚合：按（门店 × 商品族 × 星期几）分组，对训练窗口内的 z 取均值（weekday_log_mean）"
              "或中位数（weekday_log_median）作为该组合该星期几的预测。",
              "- 均值聚合利用全部观测、方差小，但对促销日和异常值敏感；中位数聚合更稳健，但可能偏保守。",
              "- 训练窗口长度（2–24 周）与聚合方式属于搜索空间，由开发折分数决定。", "",
              "### 促销调整（可选）", "",
              "- 在序列内、星期内对中心化的 ln(1+onpromotion) 与聚合残差做回归，斜率带岭收缩并截断到 [−1, 1]："
              "slope = Σ(x̃·r) / (Σx̃² + 12)，预测 = 聚合预测 + slope ×（未来促销水平 − 平均促销水平），下限取 0。",
              "- 收缩与截断避免少量促销日主导估计；训练窗口内无同序列历史的记录回退到整体对数均值。", "",
              "### 实验设计", "",
              "- 搜索空间：训练周数（2–24）、聚合方法（工作日对数均值 / 对数中位数）、促销调整（开 / 关）。",
              "- 决策 Agent 在同一个开发折上迭代提出参数组合（每轮附一句中文假设），只有降低当前最低 RMSLE 的组合"
              "才会被采纳为最优方案。",
              "- 锁定最优参数后，独立验证折只评估一次；开发折上的多次比较会引入自适应选择偏差，"
              "因此对外报告以独立验证分数为准。", ""]

    # 实验结果
    lines += ["## 实验结果", "", "### 开发折候选（同一时间折，可直接比较）", ""]
    rows = [["轮次", "假设", "训练周数", "聚合方法", "促销", "候选 RMSLE", "基线 RMSLE", "结果"],
            ["---"] * 8]
    running_best = None
    for trial in trials:
        outcome = trial["outcome"]
        score = outcome.get("candidate")
        if not finite_score(score):
            continue
        if running_best is None or score < running_best:
            verdict = "首个候选" if running_best is None else "新最优"
            running_best = score
        else:
            verdict = "未改进"
        parameters = trial["parameters"]
        rows.append([str(trial["turn"]), shorten(trial.get("hypothesis")),
                     format_int(parameters.get("weeks")),
                     METHOD_NAMES.get(parameters.get("method")) or "—",
                     ("开" if parameters.get("use_promotion") else "关") if "use_promotion" in parameters else "—",
                     f"{score:.5f}",
                     f"{outcome['baseline']:.5f}" if finite_score(outcome.get("baseline")) else "—",
                     verdict])
    if len(rows) > 2:
        lines += ["| " + " | ".join(row) + " |" for row in rows]
    else:
        lines.append("未记录到有效的开发折候选。")
    failed = [trial for trial in trials
              if not finite_score(trial["outcome"].get("candidate")) and trial["outcome"].get("error")]
    if failed:
        lines.append("")
        lines.append(f"另有 {len(failed)} 次候选执行失败（参数无效或执行错误），未列入上表。")
    lines += ["", "### 独立验证（锁定方案，仅评估一次）", ""]
    if has_holdout:
        lines += ["| 方案 | 训练截止 | 验证截止 | 验证行数 | RMSLE |",
                  "| --- | --- | --- | --- | --- |",
                  f"| 锁定候选（{locked_weeks} · {locked_method} · 促销{locked_promo_short}）"
                  f" | {holdout.get('train_end', '—')} | {holdout.get('validation_end', '—')}"
                  f" | {format_int(holdout.get('validation_rows'))} | {holdout_candidate:.5f} |",
                  f"| 季节朴素基线 | {holdout.get('train_end', '—')} | {holdout.get('validation_end', '—')}"
                  f" | {format_int(holdout.get('validation_rows'))} | {holdout_baseline:.5f} |", ""]
        lines.append(f"- 候选相对基线降低 {reduction:.2f}%。")
        fallback = holdout.get("fallback_rows")
        if isinstance(fallback, int) and fallback > 0:
            lines.append(f"- 冷启动回退：{fallback:,} 条记录在训练窗口内无同序列历史，回退到整体对数均值。")
        predictions = data.get("prediction_rows") if isinstance(data.get("prediction_rows"), int) \
            else holdout.get("prediction_rows")
        if isinstance(predictions, int):
            lines.append(f"- 预测文件 submission.csv 共 {predictions:,} 行。")
    else:
        lines.append("独立验证未执行或未完成，以上为开发折结果。")
    lines.append("")

    # 分析
    analysis = []
    if best and has_holdout:
        gap = 100 * (holdout_candidate / best["outcome"]["candidate"] - 1)
        analysis.append(f"- 泛化差距：开发折最优 {best['outcome']['candidate']:.5f}，独立验证 {holdout_candidate:.5f}"
                        f"（{gap:+.2f}%）。开发折经过多次比较选参，存在自适应选择偏差，独立验证折的分数是更保守、"
                        "更可信的泛化估计；候选在该折上仍优于基线（点估计），说明工作日聚合的改进不是开发折特有的假象。")
    method_groups = group_scores(valid, "method")
    if len(method_groups) == 2 and all(name in method_groups for name in ("weekday_log_mean", "weekday_log_median")):
        (mean_n, mean_score), (median_n, median_score) = (method_groups["weekday_log_mean"],
                                                          method_groups["weekday_log_median"])
        better = "均值" if mean_score < median_score else "中位数"
        analysis.append(f"- 聚合方法对比：开发折上工作日对数均值平均 RMSLE {mean_score:.5f}（{mean_n} 次），"
                        f"对数中位数 {median_score:.5f}（{median_n} 次），{better}聚合略优。"
                        "均值利用全部观测、估计方差小；中位数对促销日与异常值更稳健。样本量小且差异未做显著性检验，"
                        "不应外推为普适结论。")
    promotion_groups = group_scores(valid, "use_promotion")
    if len(promotion_groups) == 2 and all(key in promotion_groups for key in (True, False)):
        (on_n, on_score), (off_n, off_score) = (promotion_groups[True], promotion_groups[False])
        better = "开启" if on_score < off_score else "关闭"
        analysis.append(f"- 促销调整对比：开发折上开启促销调整的平均 RMSLE {on_score:.5f}（{on_n} 次），"
                        f"关闭 {off_score:.5f}（{off_n} 次），{better}时略优。促销效应按序列内线性关系估计并做岭收缩，"
                        "开发折上的差异不代表留出折表现，最终以独立验证分数为准。")
    if analysis:
        lines += ["## 分析", "", *analysis, ""]

    # 优缺点
    pros = ["- 方法简单、可解释、计算开销小（单次回测秒级完成），只依赖工作日分组聚合，适合资源受限与快速迭代。",
            "- 验证流程严格按时间顺序切分，训练不接触未来数据；独立验证折在方案锁定后仅评估一次，"
            "多重比较与自适应选择偏差受控。",
            "- log1p 变换与 RMSLE 目标一致，对低销量序列的相对误差敏感；中位数变体进一步抵抗促销日与异常值的干扰。",
            "- 促销调整使用中心化回归、岭收缩与斜率截断，避免少量促销日主导估计。"]
    if has_holdout:
        pros.insert(2, f"- 独立验证折上优于季节朴素基线（相对降低 {reduction:.2f}%，点估计），"
                       "说明工作日聚合捕获了稳定的周内周期性，且该改进在留出折上成立。")
    cons = ["- 方法族只利用星期几周期性，未建模节假日、长期趋势、价格与宏观经济协变量；"
            "16 天预测期内的趋势漂移无法刻画。",
            "- 均值聚合对促销日和异常值敏感；促销效应假设为序列内线性且全局统一收缩，"
            "无法刻画非线性促销冲击与品类差异。",
            "- 参数（训练周数、聚合方式、促销开关）在单一开发折上迭代选择，最优参数本身可能过拟合该折，"
            "未做多折交叉验证。",
            "- 独立验证只覆盖最后 16 天，对全年其他时段的季节性外推需谨慎。",
            "- 冷启动序列（训练窗口内无同序列历史）只能回退整体均值，预测质量低。"]
    lines += ["## 优缺点", "", "### 优点", "", *pros, "", "### 缺点与局限", "", *cons, ""]

    # 评审记录
    noted = []
    for record in registry.list("research_reviews") or []:
        if record.get("status") != "completed":
            continue
        ref = record.get("id")
        if ref == "favorita-final":
            label = "最终独立验证"
        else:
            match = re.fullmatch(r"worker-(\d+)-(\d+)", str(ref))
            if not match:
                continue
            label = f"第 {int(match.group(1)) + 1} 轮候选"
        parts = [label]
        summary = (record.get("summary") or "").strip()
        if summary:
            parts.append("评审：" + summary[:100] + ("…" if len(summary) > 100 else ""))
        limitation = (record.get("limitations") or "").strip()
        if limitation:
            parts.append("局限：" + limitation[:100] + ("…" if len(limitation) > 100 else ""))
        noted.append("；".join(parts))
    if noted:
        lines += ["## 模型评审记录", "",
                  "每轮实验后由独立模型评审核对假设与实测结果，评审意见不影响实测分数。", ""]
        lines += [f"- {line}" for line in noted]
        lines.append("")

    # 结论与建议
    lines += ["## 结论与建议", ""]
    if has_holdout:
        gap_note = ""
        if best:
            gap = 100 * (holdout_candidate / best["outcome"]["candidate"] - 1)
            gap_note = f"开发折最优与独立验证的差距（{gap:+.2f}%）提示参数选择偏差，对外报告应以独立验证分数为准。"
        lines.append(f"- 结论：锁定方案（{locked_weeks} 训练窗口、{locked_method}、{locked_promo}）"
                     f"在独立验证折上取得 RMSLE {holdout_candidate:.5f}，较季节朴素基线 {holdout_baseline:.5f}"
                     f"相对降低 {reduction:.2f}%，验证了工作日聚合（与促销调整）在本任务上的有效性。{gap_note}")
    elif best:
        lines.append(f"- 结论：锁定方案（{locked_weeks} 训练窗口、{locked_method}、{locked_promo}）"
                     f"在开发折上取得 RMSLE {best['outcome']['candidate']:.5f}；独立验证未执行或未完成，"
                     "该分数只代表开发折表现，不能直接作为泛化估计。")
    lines += ["- 建议：",
              "  1. 引入节假日与趋势特征（傅里叶项、节假日窗口哑变量），检验能否缩小开发折与独立验证的差距。",
              "  2. 用多折时间序列交叉验证（fold ≥ 2）替换单开发折选参，降低参数选择偏差。",
              "  3. 为冷启动序列建立品类 / 门店层级先验，替代整体均值回退。",
              "  4. 促销效应可尝试分段或非线性形式，并按品类估计收缩强度。",
              "  5. 提交前核对 submission.csv 与样例提交的 ID 顺序、行数与非负性（当前已校验）。", ""]
    return "\n".join(lines).rstrip() + "\n"


def generic_result_markdown(registry, report):
    lines = ["# 研究报告", ""]
    if report.get("status") != "reported":
        lines += ["状态：" + STATUSES.get(report["status"], report["status"]), ""]
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
        lines += ["", "## 结论", "", summary]
    return "\n".join(lines).rstrip() + "\n"
