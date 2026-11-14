"""Task-scoped conversational recall over durable research events and exchanges."""
import json
import re
import uuid

from fastapi import HTTPException
from pydantic import Field

from .models import Record
from .results import result_markdown
from .science.budget import BudgetExceeded, BudgetGovernor
from .science.schemas import ScienceBudget

STAGES = {"plan": "研究规划", "hypothesis": "提出假设", "execution": "实验或分析",
          "validation": "独立验证", "revision": "修正"}
RELATED = {"execution": ("hypothesis", "plan"), "validation": ("hypothesis", "execution"),
           "revision": ("validation", "hypothesis", "execution"), "hypothesis": ("plan", "revision")}


class Question(Record):
    stage_id: str | None = None
    round_id: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=1, max_length=1500)


class Answer(Record):
    answer: str = Field(min_length=1, max_length=4500)


def workflow(events, status):
    latest = next((e for e in reversed(events) if e["stage"] in STAGES), {})
    nodes = []
    for stage, name in STAGES.items():
        records = [e for e in events if e["stage"] == stage]
        state = "待执行"
        if records:
            last = records[-1]
            outcome = last.get("outcome", {})
            state = "已完成"
            if outcome.get("error"):
                state = "执行失败"
            elif outcome.get("verdict") == "refuted":
                state = "验证未通过"
            elif last == latest and status == "running":
                state = "执行中"
            elif last == latest and status == "failed":
                state = "执行失败"
        nodes.append(dict(id=stage, name=name, status=state, records=records))
    return nodes


def terms(text):
    parts = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower())
    return {t for p in parts for t in ([p] if p.isascii() or len(p)==1 else
            [p[i:i+2] for i in range(len(p)-1)])}


def context_for(registry, question):
    task = registry.get("task")
    events = registry.get("events") or []
    stage, turn = question.stage_id, question.round_id
    keywords = terms(question.message)
    def select(rows, count, width):
        ranked = []
        for i, row in enumerate(rows):
            value = json.dumps(row, ensure_ascii=False)
            overlap = len(keywords & terms(value))
            score = min(12, overlap) + 4 * (row.get("stage") == stage) + 3 * (
                row.get("stage") in RELATED.get(stage, ())) + 5 * (turn is not None and row.get("round")==turn)
            if "answer" in row:
                excerpt = {"id": row["id"], "stage": row["stage"], "round": row["round"],
                           "message": row["message"][:width//3], "answer": row["answer"][:width*2//3]}
            else:
                excerpt = value[:width]
            ranked.append((score, i, excerpt))
        return [v for _, _, v in sorted(ranked, reverse=True)[:count]]
    records = [e for e in events if e["stage"] in STAGES or e["stage"]=="conclusion"]
    plans = [e for e in records if e["stage"]=="plan"]
    aligned = [e for e in records if turn is None or e.get("round")==turn]
    exchanges = registry.list("exchanges")
    recent = exchanges[-3:]
    return {"recent_dialogue": [{"user": x["message"][:700], "assistant": x["answer"][:1200]} for x in recent],
            "verified_result": result_markdown(registry, registry.get("report"))[:3500],
            "goal":task["goal"], "domain":task.get("domain",""), "question":question.message,
            "stage":stage, "round":turn, "plan":select(plans,1,700),
            "node_records":select([e for e in aligned if e["stage"]==stage],3,800),
            "round_evidence":select([e for e in aligned if e["stage"] in ("execution","validation")],3,900),
            "cross_stage":select([e for e in records if e["stage"]!=stage],4,700),
            "memory":select(exchanges[:-3],3,1200),
            "files":task.get("files",[])}


def ask(service, id, question):
    registry = service.registry(id)
    if question.stage_id is not None and question.stage_id not in STAGES:
        raise HTTPException(422, "未知阶段")
    if question.round_id is not None and not any(e.get("round")==question.round_id and
            e["stage"]==question.stage_id for e in registry.get("events") or []):
        raise HTTPException(422, "当前阶段没有该轮记录")
    budget = BudgetGovernor(registry, ScienceBudget.model_validate(registry.get("task")["budget"]))
    with budget.discussion_time():
        return answer_question(service, registry, question, budget)


def answer_question(service, registry, question, budget):
    gateway = service.gateway_factory(service.config, registry, budget, allow_reporting=True)
    context = context_for(registry, question)
    key = uuid.uuid4().hex
    failure = "模型未配置"
    for role in ("local", "cloud"):
        endpoint = getattr(service.config, role)
        if not (endpoint.enabled and endpoint.base_url and endpoint.model):
            continue
        try:
            reply = gateway.ask(role, f"chat-{key}-{role}", "Answer the user's question in their language. "
                "Use verified_result for actual findings and numbers. Resolve follow-ups using recent_dialogue in chronological order. Distinguish verified results from suggestions. Cite record IDs where available.", context, Answer)
        except BudgetExceeded as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            failure = str(exc)
            continue
        exchange = dict(id=key, stage=question.stage_id, round=question.round_id,
                        message=question.message, answer=reply.answer)
        registry.put("exchanges", exchange, key)
        service.emit(registry, "chat", exchange_id=key, stage_id=question.stage_id)
        return exchange
    raise HTTPException(502, failure)
