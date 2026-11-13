import json
import operator
import time
from queue import Empty, Queue
from threading import Thread
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .adapters import ResearchAdapter
from .model_gateway import Decision, ModelGateway, Prompts, Role
from .models import Candidate, Evidence, Plan, ResearchTask, Result, Revision, Validation
from .storage import Storage


class BranchOutput(TypedDict):
    batch: Annotated[list[dict], operator.add]


class Branch(BranchOutput):
    run_id: str
    deadline: float
    candidate: dict


class State(TypedDict, total=False):
    run_id: str
    deadline: float
    task: dict
    plan: dict
    plan_source: str
    evidence: list[dict]
    round: int
    queue: list[dict]
    batch: Annotated[list[dict], operator.add]
    results: list[dict]
    candidates: list[dict]
    validation: dict
    revisions: list[dict]
    stalled: int
    tools: int
    stop_reason: str


def within_deadline(operation, deadline: float):
    remaining = deadline - time.time()
    if remaining <= 0:
        raise TimeoutError("运行时限已到")
    completed = Queue(maxsize=1)

    def invoke():
        try:
            completed.put((True, operation(remaining)))
        except Exception as error:
            completed.put((False, error))

    Thread(target=invoke, daemon=True).start()
    try:
        succeeded, value = completed.get(timeout=remaining)
    except Empty:
        raise TimeoutError("运行时限已到") from None
    if not succeeded:
        raise value
    return value


class Workflow:
    def __init__(self, adapter: ResearchAdapter, storage: Storage,
                 prompts: Prompts, gateway: ModelGateway | None, local_gateway: ModelGateway | None = None):
        self.adapter = adapter
        self.storage = storage
        self.prompts = prompts
        self.gateway = gateway
        self.local_gateway = local_gateway

    def compile(self, checkpointer):
        branch = StateGraph(Branch, output_schema=BranchOutput)
        branch.add_node("execute", self.execute)
        branch.add_edge(START, "execute")
        branch.add_edge("execute", END)

        graph = StateGraph(State)
        for node in (self.plan, self.collect, self.propose, self.reserve,
                     self.aggregate, self.verify, self.revise, self.finish):
            graph.add_node(node.__name__, node)
        graph.add_node("candidate", branch.compile(), input_schema=Branch)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", lambda s: "finish" if s.get("stop_reason") else "collect",
                                    ["finish", "collect"])
        graph.add_conditional_edges("collect", self.continue_or_finish, ["propose", "finish"])
        graph.add_conditional_edges("propose", lambda s: "reserve" if s["queue"] else "finish",
                                    ["reserve", "finish"])
        graph.add_conditional_edges("reserve", self.fan_out, ["candidate"])
        graph.add_edge("candidate", "aggregate")
        graph.add_conditional_edges("aggregate", self.after_batch, ["reserve", "verify"])
        graph.add_conditional_edges("verify", lambda s: "finish" if s.get("stop_reason") else "revise",
                                    ["finish", "revise"])
        graph.add_conditional_edges("revise", self.continue_or_finish, ["propose", "finish"])
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=checkpointer)

    def emit(self, state: State, stage: str, **details):
        self.storage.emit(state["run_id"], stage, round=state.get("round", 0), **details)

    @staticmethod
    def continue_or_finish(state: State) -> str:
        return "finish" if state.get("stop_reason") else "propose"

    def plan(self, state: State) -> dict:
        task = ResearchTask.model_validate(state["task"])
        if time.time() >= state["deadline"]:
            return {"stop_reason": "time_budget"}
        if self.gateway and self.prompts.planning.strip():
            name = "cloud-planning"
            context = {
                "operation": "research_plan",
                "goal": task.goal,
                "tools": sorted(self.adapter.tools),
                "resource_count": len(task.resources),
                "limits": {"rounds": task.budget.rounds, "tools": task.budget.tools,
                           "seconds": task.budget.seconds},
            }
            record = self.storage.get(state["run_id"], name)
            if record is None:
                record = self.request_cloud(state, "planning", name, self.prompts.planning,
                                            context, task.budget)
            if record and record.get("plan"):
                plan = Plan.model_validate(record["plan"])
                self.emit(state, "plan", **plan.model_dump(), source="cloud")
                return {"plan": plan.model_dump(), "plan_source": "cloud"}
            if record:
                self.emit(state, "cloud_skipped", role="planning", reason="plan_unavailable")
        try:
            plan = within_deadline(lambda _: self.adapter.plan(task), state["deadline"])
        except TimeoutError:
            return {"stop_reason": "time_budget"}
        self.emit(state, "plan", **plan.model_dump(), source="adapter")
        return {"plan": plan.model_dump(), "plan_source": "adapter"}

    def collect(self, state: State) -> dict:
        task = ResearchTask.model_validate(state["task"])
        plan = Plan.model_validate(state["plan"])
        try:
            evidence = within_deadline(lambda _: self.adapter.collect(task, plan), state["deadline"])
        except TimeoutError:
            return {"stop_reason": "time_budget"}
        records = [item.model_dump() for item in evidence]
        self.emit(state, "evidence", evidence=records)
        return {"evidence": records}

    def limit(self, state: State) -> str | None:
        budget = ResearchTask.model_validate(state["task"]).budget
        if time.time() >= state["deadline"]:
            return "time_budget"
        if state.get("tools", 0) >= budget.tools:
            return "tool_budget"
        return None

    def propose(self, state: State) -> dict:
        reason = self.limit(state)
        if reason:
            return {"queue": [], "stop_reason": reason}
        revisions = state.get("revisions", [])
        revision = Revision.model_validate(revisions[-1]) if revisions else None
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        known_ids = {item["id"] for item in state.get("candidates", [])}
        evidence_ids = {item.id for item in evidence}
        options = []
        try:
            proposed = within_deadline(lambda _: self.adapter.propose(evidence, revision), state["deadline"])
        except TimeoutError:
            return {"queue": [], "stop_reason": "time_budget"}
        for candidate in proposed:
            if candidate.id in known_ids or candidate.tool not in self.adapter.tools:
                continue
            if not set(candidate.evidence_ids) <= evidence_ids:
                continue
            known_ids.add(candidate.id)
            options.append(candidate.model_dump())
        if not options:
            return {"queue": [], "stop_reason": "no_candidates"}
        round_number = state.get("round", 0) + 1
        if (revision and not self.prompts.planning.strip()
                and (state["stalled"] >= 2 or state["validation"]["recoverable_unknown"])):
            options = self.model_choice(state, "diagnosis", options, round_number)
        if self.local_gateway and self.prompts.local.strip() and len(options) > 1:
            options = self.local_order(state, options, round_number)
        if time.time() >= state["deadline"]:
            return {"queue": [], "stop_reason": "time_budget"}
        self.emit({**state, "round": round_number}, "hypothesis", candidates=options)
        return {"round": round_number, "queue": options,
                "candidates": state.get("candidates", []) + options}

    def model_choice(self, state: State, role: Role, options: list[dict], round_number: int):
        prompt = getattr(self.prompts, role)
        if self.gateway is None or not prompt.strip():
            self.emit(state, "cloud_skipped", role=role, reason="model_or_prompt_unconfigured")
            return options
        budget = ResearchTask.model_validate(state["task"]).budget
        name = f"cloud-{role}-{round_number}"
        previous = self.storage.get(state["run_id"], name)
        context = self.decision_context(state, options)
        if previous is None:
            previous = self.request_cloud(state, role, name, prompt, context, budget)
        offered = {item["id"] for item in context["actions"]}
        action = previous["action_id"] if previous else None
        return [item for item in options if item["id"] == action] if action in offered else options

    @staticmethod
    def decision_context(state: State, options: list[dict]) -> dict:
        return {
            "goal": state["task"]["goal"],
            "plan": state.get("plan", {}),
            "evidence": [{"id": item["id"], "summary": item["summary"][:500]}
                         for item in state["evidence"][-6:]],
            "recent_result": state.get("validation", {}).get("summary", "")[:500],
            "actions": [{"id": item["id"], "hypothesis": item["hypothesis"][:500]}
                        for item in options[:6]],
        }
    def request_cloud(self, state, role, name, prompt, context, budget):
        run_id = state["run_id"]
        ledger = self.cloud_ledger(run_id)
        if ledger["cloud_requests"] >= budget.cloud_requests or self.limit(state):
            self.emit(state, "cloud_skipped", role=role, reason="budget")
            return None
        try:
            reserve = within_deadline(lambda _: self.gateway.reserve(prompt, context), state["deadline"])
        except Exception:
            self.emit(state, "cloud_skipped", role=role, reason="estimate_unavailable")
            return None
        if reserve <= 0 or ledger["tokens"] + ledger["tokens_pending"] + reserve > budget.tokens:
            self.emit(state, "cloud_skipped", role=role, reason="budget")
            return None
        record = {"reserved": reserve, "usage": None, "action_id": None}
        self.storage.put(run_id, name, record)
        self.emit(state, "cloud_reserved", role=role, **self.cloud_ledger(run_id))
        self.call_model(state, self.gateway, name, prompt, context, record, "cloud", role=role)
        self.emit(state, "cloud_accounted", role=role, **self.cloud_ledger(run_id))
        return record

    def local_order(self, state: State, options: list[dict], round_number: int) -> list[dict]:
        run_id = state["run_id"]
        name = f"local-model-{round_number}"
        record = self.storage.get(run_id, name)
        context = self.decision_context(state, options)
        if record is None and not self.limit(state):
            record = {"action_id": None, "usage": None}
            self.storage.put(run_id, name, record)
            self.call_model(state, self.local_gateway, name, self.prompts.local, context, record, "local")
            self.emit(state, "local_accounted", **self.local_ledger(run_id))
        action = record["action_id"] if record else None
        if action not in {item["id"] for item in context["actions"]}:
            return options
        # Keep dependency barriers and preserve the original order of other candidates.
        for index, item in enumerate(options):
            if item["id"] == action and all(candidate["independent"] for candidate in options[:index + 1]):
                self.emit({**state, "round": round_number}, "local_choice", candidate_id=action)
                return [item, *options[:index], *options[index + 1:]]
        return options

    def call_model(self, state, gateway, name, prompt, context, record, channel, **details):
        run_id = state["run_id"]
        try:
            decision = within_deadline(
                lambda timeout: Decision.model_validate(gateway.decide(
                    prompt, context, timeout, f"{run_id}:{name}")),
                state["deadline"],
            )
            record.update(decision.model_dump())
            self.storage.put(run_id, name, record)
        except Exception as error:
            self.emit(state, f"{channel}_failed", reason=type(error).__name__, **details)

    def cloud_ledger(self, run_id: str) -> dict:
        records = self.model_records(run_id, "cloud-%")
        return {"cloud_requests": len(records),
                "tokens": sum(item["usage"] or 0 for item in records),
                "tokens_pending": sum(item["reserved"] for item in records if item["usage"] is None)}

    def local_ledger(self, run_id: str) -> dict:
        records = self.model_records(run_id, "local-model-%")
        return {"local_requests": len(records), "local_tokens": sum(item["usage"] or 0 for item in records)}

    def model_records(self, run_id: str, pattern: str) -> list[dict]:
        with self.storage.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE run_id=? AND name LIKE ?",
                              (run_id, pattern)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reserve(self, state: State) -> dict:
        budget = ResearchTask.model_validate(state["task"]).budget
        size = 1
        if len(state["queue"]) >= 2 and all(item["independent"] for item in state["queue"][:2]):
            size = 2
        size = min(size, budget.tools - state.get("tools", 0))
        tools = state.get("tools", 0) + size
        self.emit(state, "execution", tools=tools, candidate_ids=[c["id"] for c in state["queue"][:size]])
        return {"tools": tools}

    def fan_out(self, state: State):
        # Only undispatched candidates are in the queue. The reserved count
        # includes previous batches, whose results have already been aggregated.
        size = state["tools"] - len(state.get("results", []))
        return [Send("candidate", {"run_id": state["run_id"], "deadline": state["deadline"],
                                    "candidate": item}) for item in state["queue"][:size]]

    def execute(self, state: Branch) -> dict:
        candidate = Candidate.model_validate(state["candidate"])
        key = f"result-{candidate.id}"
        stored = self.storage.get(state["run_id"], key)
        if stored is not None:
            return {"batch": [stored]}
        artifact = f"results/{candidate.id}.json"
        try:
            tool = self.adapter.tools[candidate.tool]
            data = within_deadline(
                lambda timeout: tool(candidate.parameters, timeout, f'{state["run_id"]}:{candidate.id}'),
                state["deadline"],
            )
            json.dumps(data, allow_nan=False)
            result = Result(candidate_id=candidate.id, summary="执行完成", data=data, artifact=artifact)
        except Exception as error:
            result = Result(candidate_id=candidate.id, summary="执行失败",
                            error=f"{type(error).__name__}: {str(error)[:400]}", artifact=artifact)
        record = result.model_dump()
        self.storage.put(state["run_id"], key, record)
        return {"batch": [record]}

    def aggregate(self, state: State) -> dict:
        prior = state.get("results", [])
        by_id = {item["candidate_id"]: item for item in state["batch"]}
        size = state["tools"] - len(prior)
        added = [by_id[item["id"]] for item in state["queue"][:size]]
        evidence = [Evidence(id=f'result-{item["candidate_id"]}',
                             summary=item["error"] or item["summary"],
                             artifact=item["artifact"]).model_dump() for item in added]
        self.emit(state, "results", results=added, evidence=evidence)
        return {"results": prior + added, "queue": state["queue"][size:],
                "evidence": state["evidence"] + evidence}

    def after_batch(self, state: State) -> str:
        return "reserve" if state["queue"] and not self.limit(state) else "verify"

    def verify(self, state: State) -> dict:
        previous = Validation.model_validate(state["validation"]) if "validation" in state else None
        results = [Result.model_validate(item) for item in state["results"]]
        try:
            validation = within_deadline(lambda _: self.adapter.verify(results, previous), state["deadline"])
        except TimeoutError:
            return {"stop_reason": "time_budget"}
        budget = ResearchTask.model_validate(state["task"]).budget
        reason = "validated" if validation.passed else self.limit(state)
        if reason is None and state["round"] >= budget.rounds:
            reason = "round_budget"
        record = validation.model_dump()
        self.emit(state, "validation", validation=record)
        return {"validation": record, "stalled": 0 if validation.improved else state.get("stalled", 0) + 1,
                **({"stop_reason": reason} if reason else {})}

    def revise(self, state: State) -> dict:
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        validation = Validation.model_validate(state["validation"])
        try:
            revision = within_deadline(lambda _: self.adapter.revise(validation, evidence), state["deadline"])
        except TimeoutError:
            return {"stop_reason": "time_budget"}
        if not set(revision.evidence_ids) <= {item.id for item in evidence}:
            raise ValueError("修正引用了未知证据")
        record = revision.model_dump()
        self.emit(state, "revision", revision=record)
        return {"revisions": state.get("revisions", []) + [record]}

    def finish(self, state: State) -> dict:
        return {"stop_reason": state.get("stop_reason", "completed")}
