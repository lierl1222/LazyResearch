"""Budgeted selection on a development fold, followed by a locked evaluation."""
from itertools import product
from math import isfinite
from typing import get_args

from pydantic import Field

from .iteration import stop_reason as iteration_limit
from .model_context import compact_text
from .presentation import explain_reason
from .research_tools import execute_tool
from .science.budget import BudgetExceeded
from .science.execution import execute_isolated
from .tools.forecasting import ForecastParameters, finalize_favorita


class ForecastChoice(ForecastParameters):
    hypothesis: str = Field(min_length=1, max_length=300)


def search_favorita(task, material, registry, budget, tool, ask, emit, evidence, reports, result,
                    previous_research=()):
    fields = ForecastParameters.model_fields
    methods = get_args(fields["method"].annotation)
    limits = fields["weeks"].metadata
    lower = next(limit.ge for limit in limits if hasattr(limit, "ge"))
    upper = next(limit.le for limit in limits if hasattr(limit, "le"))
    attempted = set()
    trials = []
    best = None
    reserves_final = task.budget.max_experiments > 1
    candidate_limit = min(task.max_delegations, task.budget.max_experiments - reserves_final)
    stop_reason = ("已完成设定的研究轮次。" if candidate_limit == task.max_delegations
                   else "已达到本次候选实验额度。")
    recent_errors = []

    def key(parameters):
        return parameters["weeks"], parameters["method"], parameters["use_promotion"]

    for turn in range(candidate_limit):
        if budget.stop_requested():
            return result("stopped", explain_reason("user_stop"))
        limit = iteration_limit(task,budget,turn,int(reserves_final))
        if limit:
            stop_reason = limit
            break
        if budget.remaining_time() <= 0:
            stop_reason = explain_reason("wall_time_budget")
            break
        context = {"goal": task.goal, "metric": "RMSLE", "optimization": "minimize",
                   "best": best, "trials": trials[-8:], "attempted": sorted(attempted),
                   "recent_errors": recent_errors[-2:], "candidate_rounds_left": candidate_limit - turn,
                   "previous_research": compact_text(list(previous_research)[-1:], 240),
                   "data": "逐日销量、门店、商品族、促销，预测期 16 天"}
        instruction = ("你是决策 Agent。根据已测分数和失败反馈，提出一组从未试过的参数，目标是最小化 RMSLE。"
                       "所有候选使用同一个时间开发折。可改变训练周数、同星期几的聚合方式、是否使用促销。"
                       "先试有根据的方案，再围绕最佳方案改进或探索差异较大的方案。假设用一句简短中文。")
        args = None
        source = "决策 Agent"
        for attempt in ("", "-retry"):
            try:
                choice = ask(f"director-{turn}{attempt}", instruction, context, ForecastChoice)
            except (BudgetExceeded, RuntimeError) as error:
                source = "本机补选 · " + explain_reason(str(error))
                break
            proposed = choice.model_dump(exclude={"hypothesis"})
            if key(proposed) not in attempted:
                args = proposed
                hypothesis = choice.hypothesis
                break
            source = "本机补选 · 决策 Agent 提交了重复参数"
            context = {**context, "rejected_duplicate": proposed}
            instruction += " 刚才的组合已试过。必须改变至少一个参数，优先比较尚未覆盖的方法或促销设置。"
        if args is not None:
            source = "决策 Agent"
        if budget.stop_requested():
            return result("stopped", explain_reason("user_stop"))
        if args is None:
            center = key(best["parameters"]) if best else (lower + (upper - lower) // 3, methods[0], False)
            choices = (item for item in product(range(lower, upper + 1), methods, (False, True))
                       if item not in attempted)
            used_settings = {(method, promotion) for _, method, promotion in attempted}
            def priority(item):
                weeks, method, promotion = item
                different = (method != center[1]) + (promotion != center[2])
                distance = abs(weeks - center[0])
                if len(used_settings) < 4:
                    return (item[1:] in used_settings, different, distance, item)
                nearest = min((abs(weeks - tested[0]) for tested in attempted if tested[1:] == item[1:]),
                              default=upper - lower)
                return (False, different, distance - 2 * nearest, item)
            weeks, method, promotion = min(choices, key=priority)
            args = dict(weeks=weeks, method=method, use_promotion=promotion)
            hypothesis = "比较尚未覆盖的参数设置，检验是否能降低开发折 RMSLE。"

        id = f"worker-{turn}-0"
        round_number = turn + 1
        label = tool.label
        emit("plan", round=round_number, summary=f"{source}。{hypothesis}")
        if turn:
            reference = (f"当前最低开发折 RMSLE 为 {best['candidate']:.5f}，继续验证新的参数组合。"
                         if best else "根据上轮执行反馈调整参数，继续验证。")
            emit("revision", round=round_number, summary=reference)
        emit("hypothesis", round=round_number, summary=hypothesis,
             prediction="新方案在同一开发折上的 RMSLE 更低。", tool_label=label)
        emit("execution", round=round_number, summary="favorita_candidate", tool_label=label,
             observation_id=id, arguments=args)
        try:
            outcome = execute_isolated(registry, budget, id, execute_tool,
                                       {"tool": "favorita_candidate", "tool_spec": tool.model_dump(by_alias=True),
                                        "arguments": args, "task": material})
        except BudgetExceeded as error:
            stop_reason = explain_reason(str(error))
            break
        attempted.add(key(args))
        score = outcome.get("candidate")
        if not outcome.get("error") and isinstance(score, (int, float)) and isfinite(score) and score >= 0:
            validation_fold = ("train_end", "validation_end", "validation_rows")
            if best and any(outcome.get(k) != evidence[best["id"]].get(k) for k in validation_fold):
                outcome = {**outcome, "error": "候选与现有方案的开发折不同，无法比较。"}
            else:
                if best:
                    outcome = {**outcome, "previous_best_rmsle": best["candidate"],
                               "improved": score < best["candidate"],
                               "verdict": "supported" if score < best["candidate"] else "refuted"}
                trial = {"id": id, "parameters": args, "candidate": score, "source": source}
                trials.append(trial)
                if best is None or score < best["candidate"]:
                    best = trial
        else:
            outcome = {**outcome, "error": outcome.get("error") or "未取得有效 RMSLE。"}
        if outcome.get("error"):
            recent_errors.append(outcome["error"])
        evidence[id] = outcome
        reports.append({"objective": hypothesis, "parameters": args, "observation_id": id, "source": source})
        emit("validation", round=round_number, observation_id=id, tool_label=label, outcome=outcome)

    if budget.stop_requested():
        return result("stopped", explain_reason("user_stop"))
    if best is None:
        return result("inconclusive", f"{stop_reason} 未取得有效的开发折 RMSLE。")

    summary = f"{stop_reason} 共测得 {len(trials)} 个有效候选，最低开发折 RMSLE 为 {best['candidate']:.5f}。"
    if not reserves_final:
        return result("reported", summary + " 独立验证需要另一次实验额度。", [best["id"]])
    emit("execution", round=len(reports) + 1, summary="锁定方案后执行独立验证",
         tool_label="Favorita 最终独立验证", observation_id="favorita-final", arguments=best["parameters"])
    try:
        final = execute_isolated(registry, budget, "favorita-final", finalize_favorita,
                                 {"task": material, "arguments": best["parameters"], "trials": trials})
    except BudgetExceeded as error:
        return result("reported", summary + " 独立验证未执行：" + explain_reason(str(error)) + "。", [best["id"]])
    evidence["favorita-final"] = final
    emit("validation", round=len(reports) + 1, observation_id="favorita-final",
         tool_label="Favorita 最终独立验证", outcome=final)
    if final.get("error"):
        status = "stopped" if final["error"] == "user_stop" else "reported"
        return result(status, summary + " 独立验证未完成：" + explain_reason(final["error"]) + "。", [best["id"]])
    return result("reported", summary + f" 锁定方案的独立验证 RMSLE 为 {final['candidate']:.5f}。",
                  [best["id"], "favorita-final"])
