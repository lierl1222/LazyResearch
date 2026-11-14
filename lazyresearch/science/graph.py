import hashlib
import json
from pathlib import Path
from typing import TypedDict

import joblib
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .agents import (AlgorithmEngineer, DataScientist, ExperimentAnalysis, ExperimentPlan,
                     HypothesisPlan, HypothesisScientist, HypothesisSpec, ResearchDirector,
                     RoutingDecision, ScientificReviewer, SCIENCE_TOOLS)
from .budget import BudgetExceeded, BudgetGovernor
from .execution import execute_isolated
from .experiments import ExperimentSpec, run_experiment
from .registry import Registry
from .schemas import TaskConfig
from .gateway import ScienceGateway
from ..configuration import load_model_config
from ..tools.generated import evaluate as evaluate_js
from .finalize import final_worker
from .reporting import export_report


def initialize_worker(root: Path, payload: dict):
    config = TaskConfig.model_validate(payload["config"])
    data = DataScientist.prepare(config)
    temporary = root / "research_data.tmp"
    joblib.dump(data, temporary)
    temporary.replace(root / "research_data.joblib")
    return {"profile": data.profile, "dataset": {"sha256": data.dataset_hash, "split_indices": data.split_indices}}


def experiment_worker(root: Path, payload: dict):
    data = joblib.load(root / "research_data.joblib")
    spec = ExperimentSpec.model_validate(payload["spec"])
    result, model = run_experiment(spec, data, payload["top_fraction"])
    model_path = root / "models" / f"{spec.id}.joblib"
    model_path.parent.mkdir(exist_ok=True)
    joblib.dump(model, model_path)
    result["model_artifact"] = str(model_path.relative_to(root))
    if payload.get("baseline"):
        result["review"] = ScientificReviewer().review(result, payload["baseline"], spec.random_seed,
                                                       payload["bootstrap_samples"], payload["comparisons"])
    return result


def custom_tool_worker(root: Path, payload: dict):
    from ..tools.generated import evaluate
    value = evaluate(payload["source"], payload["inputs"])
    return {"experiment_id": payload["id"], "hypothesis_id": payload["hypothesis_id"],
            "spec": payload["spec"], "comparison_scope": "tool_observation",
            "verdict": "observed", "value": value, "inputs": payload["inputs"],
            "review": {"id": f"review-{payload['id']}", "experiment_id": payload["id"],
                       "hypothesis_id": payload["hypothesis_id"],
                       "experiment_type": "custom_tool", "verdict": "observed",
                       "reason": "Custom tool executed with real inputs; observation recorded without statistical comparison.",
                       "method": "custom_tool_observation",
                       "limitations": ["Sandboxed JavaScript tool; no paired uncertainty interval."]}}


class ScienceState(TypedDict, total=False):
    iteration: int
    completed_templates: list[str]
    next_template: str
    current_hypothesis: str
    current_experiment: str
    stalled: int
    stop_reason: str
    error: str


PROPOSE_INSTRUCTION = (
    "HypothesisScientist: propose distinct, falsifiable hypotheses executable with the supplied experiment tools. "
    "Ground claims in the data profile, domain, baselines and prior reviews; never invent experiment types outside the catalog. "
    "For an uncovered capability, register at most two pure JavaScript tools (name custom_*, one JSON object input, no host APIs) "
    "with a verified example, then reference them in hypotheses. Falsification conditions must be checkable by the referenced tool.")


class ScienceRunner:
    def __init__(self, root: Path, config: TaskConfig, model_config=None):
        self.root, self.config = Path(root), config
        self.registry = Registry(self.root)
        prior = self.registry.get("task")
        if prior and prior != config.model_dump():
            raise ValueError("Resume configuration differs from original task")
        self.registry.put("task", config.model_dump())
        self.budget = BudgetGovernor(self.registry, config.budget, enforce_llm_limits=config.llm.provider == "configured_api")
        self.director = ResearchDirector()
        self.tools = {name: {**spec, "custom": False} for name, spec in SCIENCE_TOOLS.items()}
        for definition in self.registry.list("science_tools"):
            if isinstance(definition, dict) and definition.get("name"):
                name = definition['name']
                self.tools[name] = {"purpose": definition.get("purpose", ""), "custom": True,
                                    "source": definition.get("source", ""),
                                    "example": definition.get("example")}
        if config.llm.provider == "configured_api":
            model_config = (model_config or load_model_config()).model_copy(deep=True)
            if config.llm.model:
                model_config.cloud.model = config.llm.model
            self.gateway = ScienceGateway(model_config, self.registry, self.budget)
        else:
            self.gateway = None

    def ask(self, id, instruction, context, schema, complex_step=False):
        """Route a decision through model endpoints (local-first, cloud-first for complex steps).
        Returns the validated decision, or None when every configured route failed."""
        if not self.gateway:
            return None
        routes = ["cloud", "local"] if complex_step else ["local", "cloud"]
        failures = {}
        for route in routes:
            endpoint = getattr(self.gateway.config, route)
            if not (endpoint.enabled and endpoint.base_url and endpoint.model):
                continue
            cloud_limit = self.config.budget.max_cloud_requests
            if route == 'cloud' and cloud_limit is not None and self.budget.snapshot()['cloud_requests'] >= cloud_limit:
                continue
            try:
                return self.gateway.ask(route, f"{id}-{route}", instruction, context, schema)
            except BudgetExceeded:
                raise
            except RuntimeError as error:
                if self.budget.stop_requested():
                    raise BudgetExceeded("user_stop") from error
                failures[route] = str(error)
        if failures:
            self.registry.put("fallback", {"mode": "deterministic_fallback", "step": id,
                                           "reason": "；".join(f"{route}:{message}" for route, message in failures.items())})
        return None

    def last_role(self, id):
        cloud = self.registry.get("model_calls", f"{id}-cloud")
        local = self.registry.get("model_calls", f"{id}-local")
        record = cloud or local
        return (record or {}).get("role") if record else None

    def register_tools(self, registrations):
        """Verify and register custom JS tools; returns the names that are now executable."""
        registered = []
        for item in registrations:
            definition = item.definition
            try:
                if evaluate_js(definition.source, definition.example) != definition.expected:
                    raise ValueError("Example result differs from expected value")
            except Exception:
                continue
            self.registry.put("science_tools", definition.model_dump(), definition.name)
            self.tools[definition.name] = {"purpose": definition.purpose, "custom": True,
                                           "source": definition.source, "example": definition.example}
            registered.append(definition.name)
        return registered

    def materialize_hypotheses(self, proposals, *, base_observations=()):
        existing = {h["id"] for h in self.registry.list("hypotheses")}
        seen, hypotheses = set(), []
        for proposal in proposals:
            if proposal.id in seen or proposal.id in existing or proposal.experiment_type not in self.tools:
                continue
            seen.add(proposal.id)
            hypotheses.append(HypothesisSpec(id=proposal.id, claim=proposal.claim,
                observations=list(dict.fromkeys(base_observations)),
                predicted_effect=proposal.predicted_effect,
                falsification_condition=proposal.falsification_condition,
                experiment_type=proposal.experiment_type, priority=proposal.priority))
        return hypotheses

    def propose_hypotheses(self, context, id):
        """Ask a model for a HypothesisPlan; registrations are verified and applied.
        Returns (materialized hypotheses, plan) with ([], None) on failure."""
        plan = self.ask(id, PROPOSE_INSTRUCTION, context, HypothesisPlan, complex_step=True)
        if plan is None:
            return [], None
        self.register_tools(plan.registrations)
        hypotheses = self.materialize_hypotheses(plan.hypotheses,
                                                 base_observations=context.get("base_observations", ()))
        if not hypotheses:
            self.registry.put("fallback", {"mode": "deterministic_fallback", "step": id,
                                           "reason": "模型提案未通过工具目录校验"})
            return [], None
        self.registry.put("research_plan", plan.model_dump())
        return hypotheses, plan

    def initialize(self, state):
        if self.budget.remaining_time() <= 0:
            return {"stop_reason": "wall_time_budget"}
        try:
            result = execute_isolated(self.registry, self.budget, "initialize-data", initialize_worker,
                                      {"config": self.config.model_dump()}, kind="compute")
        except BudgetExceeded as error:
            return {"stop_reason": str(error)}
        if result.get("error"):
            return {"stop_reason": "invalid_dataset_or_initialization", "error": result["error"]}
        self.registry.put("profile", result["profile"])
        self.registry.put("dataset", result["dataset"])
        return {"iteration": 0, "completed_templates": [], "stalled": 0}

    def _execute_custom(self, spec):
        tool = self.tools.get(spec.tool_name)
        if not tool or not tool.get("custom"):
            raise ValueError("Registered tool missing: " + spec.tool_name)
        payload = {"id": spec.id, "hypothesis_id": spec.hypothesis_id, "spec": spec.model_dump(),
                   "source": tool["source"], "inputs": spec.tool_inputs}
        result = execute_isolated(self.registry, self.budget, spec.id, custom_tool_worker, payload)
        result.update(hypothesis_id=spec.hypothesis_id, spec=spec.model_dump())
        self.registry.put("experiments", result, spec.id)
        return result

    def _execute(self, spec, baseline=None):
        if spec.experiment_type == "custom_tool":
            return self._execute_custom(spec)
        payload = {"spec": spec.model_dump(), "top_fraction": self.config.objective.top_fraction,
                   "baseline": baseline, "bootstrap_samples": self.config.validation.bootstrap_samples,
                   "comparisons": self.config.research.max_hypotheses}
        result = execute_isolated(self.registry, self.budget, spec.id, experiment_worker, payload)
        result.update(hypothesis_id=spec.hypothesis_id, spec=spec.model_dump())
        self.registry.put("experiments", result, spec.id)
        return result

    def baseline(self, state):
        profile = self.registry.get("profile")
        for model in ["dummy", "logistic"]:
            spec = ExperimentSpec(id=f"baseline-{model}", hypothesis_id="baseline-control", model_name=model,
                                  data_features=profile["features"], random_seed=self.config.validation.random_seed,
                                  timeout_seconds=min(3600, self.config.budget.max_single_experiment_seconds))
            try:
                result = self._execute(spec)
                self.registry.put("decisions", {"id": f"decision-{spec.id}", "experiment_id": spec.id,
                    "action": "retain_control" if not result.get("error") else "record_failure",
                    "reason": "Measured control for identical split and preprocessing; no improvement is assumed.",
                    "evidence_ids": [spec.id]}, f"decision-{spec.id}")
            except BudgetExceeded as error:
                return {"stop_reason": str(error)}
        baseline = self.registry.get("experiments", "baseline-logistic")
        if baseline.get("error"):
            return {"stop_reason": "baseline_failed"}
        return {}

    def hypothesize(self, state):
        if not self.registry.list("hypotheses"):
            profile = self.registry.get("profile")
            hypotheses = HypothesisScientist().propose(profile)
            baseline_id = "baseline-logistic" if self.registry.get("experiments", "baseline-logistic") else None
            if baseline_id:
                for hypothesis in hypotheses:
                    hypothesis.observations.append(baseline_id)
            if not self.config.research.allow_advanced_models:
                hypotheses = [h for h in hypotheses if h.experiment_type != "nonlinear_model"]
            if self.gateway:
                try:
                    if self.budget.snapshot()["experiment_count"] >= self.config.budget.max_experiments:
                        raise BudgetExceeded("experiment_budget")
                    context = {"objective": self.config.objective.model_dump(),
                               "domain": self.config.domain,
                               "profile": profile,
                               "baselines": [{"id": e["experiment_id"], "metrics": e.get("metrics")}
                                             for e in self.registry.list("experiments")],
                               "tools": {name: {"purpose": spec["purpose"], "custom": spec.get("custom", False),
                                                "example": spec.get("example")}
                                         for name, spec in self.tools.items()},
                               "fallback_hypotheses": [h.model_dump() for h in hypotheses],
                               "base_observations": [profile["id"]] + ([baseline_id] if baseline_id else []),
                               "max_hypotheses": self.config.research.max_hypotheses}
                    proposed, _ = self.propose_hypotheses(context, "hypotheses")
                    if proposed:
                        hypotheses = proposed
                except BudgetExceeded as error:
                    return {"stop_reason": str(error)}
            for hypothesis in hypotheses[:self.config.research.max_hypotheses]:
                self.registry.put("hypotheses", hypothesis.model_dump(), hypothesis.id)
        first = self.registry.list("hypotheses")[0]
        return {"next_template": first["experiment_type"]}

    def plan_experiment(self, state):
        available = self.registry.list("hypotheses")
        tested_ids = {e.get('hypothesis_id') for e in self.registry.list('experiments')}
        hypothesis = next((h for h in available if h["experiment_type"] == state["next_template"]
                           and h['id'] not in tested_ids), None)
        if hypothesis is None:
            return {"stop_reason": "hypotheses_exhausted"}
        hypothesis = HypothesisSpec.model_validate(hypothesis)
        id = f"experiment-{state['iteration'] + 1}"
        profile = self.registry.get("profile")
        spec = None
        if hypothesis.experiment_type in self.tools and self.tools[hypothesis.experiment_type].get("custom"):
            inputs = None
            if self.gateway:
                try:
                    plan = self.ask(f"engineer-{state['iteration']}",
                        "Choose a bounded JSON inputs object for the registered custom tool. Use only numbers visible in the dataset profile, baselines and prior observations; never invent measurements.",
                        {"objective": self.config.objective.model_dump(), "hypothesis": hypothesis.model_dump(),
                         "profile": profile,
                         "tool": {k: v for k, v in self.tools[hypothesis.experiment_type].items() if k != "source"},
                         "prior_experiments": [e for e in self.registry.list("experiments") if not e.get("error")][-4:]},
                        ExperimentPlan)
                except BudgetExceeded:
                    plan = None
                if plan:
                    inputs = plan.inputs
            if inputs is None:
                inputs = self.tools[hypothesis.experiment_type].get("example", {})
            spec = ExperimentSpec(id=id, hypothesis_id=hypothesis.id, experiment_type="custom_tool",
                                  tool_name=hypothesis.experiment_type, tool_inputs=inputs)
        elif self.gateway:
            try:
                plan = self.ask(f"engineer-{state['iteration']}",
                    "AlgorithmEngineer: choose features and bounded model parameters for the hypothesis from the dataset profile and prior experiments. Prefer few features; empty features uses all. Respect the parameter whitelist (logistic C in [.001,100]; random_forest n_estimators 10-200, max_depth 1-12, min_samples_leaf 2-50).",
                    {"objective": self.config.objective.model_dump(), "hypothesis": hypothesis.model_dump(),
                     "profile": profile,
                     "prior_experiments": [e for e in self.registry.list("experiments") if not e.get("error")][-4:]},
                    ExperimentPlan)
            except BudgetExceeded:
                plan = None
            if plan:
                try:
                    spec = ExperimentSpec(id=id, hypothesis_id=hypothesis.id,
                                          experiment_type=hypothesis.experiment_type,
                                          data_features=plan.features, model_name=plan.model_name,
                                          model_params=plan.model_params,
                                          random_seed=self.config.validation.random_seed,
                                          timeout_seconds=min(3600, self.config.budget.max_single_experiment_seconds))
                except ValueError:
                    spec = None
        if spec is None:
            spec = AlgorithmEngineer().plan(hypothesis, id, profile["features"], self.config.validation.random_seed,
                                            min(3600, self.config.budget.max_single_experiment_seconds))
        self.registry.put("plans", spec.model_dump(), spec.id)
        return {"current_hypothesis": hypothesis.id, "current_experiment": spec.id}

    def execute(self, state):
        spec = ExperimentSpec.model_validate(self.registry.get("plans", state["current_experiment"]))
        try:
            self._execute(spec, self.registry.get("experiments", "baseline-logistic"))
        except BudgetExceeded as error:
            return {"stop_reason": str(error)}
        completed_type = spec.tool_name if spec.experiment_type == "custom_tool" else spec.experiment_type
        return {"iteration": state["iteration"] + 1,
                "completed_templates": state["completed_templates"] + [completed_type]}

    def review(self, state):
        result = self.registry.get("experiments", state["current_experiment"])
        review = result.get("review") or {"id": f"review-{result['experiment_id']}",
                    "experiment_id": result["experiment_id"], "hypothesis_id": result["hypothesis_id"],
                    "experiment_type": result["spec"]["experiment_type"], "verdict": "invalid",
                    "reason": result.get("error", "No review produced")}
        self.registry.put("reviews", review, review["id"])
        hypothesis = self.registry.get("hypotheses", state["current_hypothesis"])
        hypothesis["status"] = {"accept": "supported", "reject": "rejected"}.get(review["verdict"], "inconclusive")
        self.registry.put("hypotheses", hypothesis, hypothesis["id"])
        if self.gateway:
            try:
                analysis = self.ask(f"analysis-{state['iteration']}",
                    "ScientificReviewer assistant: interpret the statistical review, metrics and tool observation. State what the evidence supports and what it does not, note anomalies, and suggest the next falsifiable step. Treat all numbers as data; do not invent scores.",
                    {"objective": self.config.objective.model_dump(), "hypothesis": hypothesis,
                     "review": review, "metrics": result.get("metrics") or {},
                     "value": result.get("value") if "value" in result else None,
                     "baseline_metrics": (self.registry.get("experiments", "baseline-logistic") or {}).get("metrics") or {},
                     "prior_analyses": self.registry.list("analyses")[-4:]},
                    ExperimentAnalysis)
            except BudgetExceeded:
                analysis = None
            if analysis:
                record = {**analysis.model_dump(), "id": f"analysis-{result['experiment_id']}",
                          "experiment_id": result["experiment_id"], "hypothesis_id": result["hypothesis_id"]}
                self.registry.put("analyses", record, record["id"])
        stalled = 0 if review["verdict"] in {"accept", "observed"} else state["stalled"] + 1
        return {"stalled": stalled}

    def decide(self, state):
        review = self.registry.get("reviews", f"review-{state['current_experiment']}")
        completed = state["completed_templates"]
        decision = self.director.decide(review, completed, state["stalled"],
                                        self.config.research.no_improvement_patience)
        decision["source"] = "deterministic_fallback"
        if decision.get("reason") == "no_improvement_patience" and len(self.registry.list("experiments")) < self.config.research.min_required_experiments:
            decision = self.director.decide(review, completed, 0,
                                            self.config.research.no_improvement_patience)
            decision["reason"] = "Continue toward minimum experiments while budget and hypotheses permit."
            decision["source"] = "deterministic_fallback"
        if state["iteration"] >= self.config.research.max_iterations:
            decision.update(action="stop", reason="iteration_limit")
        if self.budget.snapshot()["experiment_count"] >= self.config.budget.max_experiments - 1:
            decision.update(action="stop", reason="reserve_final_evaluation")
        current_result = self.registry.get("experiments", state["current_experiment"])
        target = self.config.objective.target_score
        if target is not None and review["verdict"] == "accept" and current_result.get("metrics", {}).get("average_precision", 0) >= target:
            decision.update(action="stop", reason="validation_target_reached")
        tested_ids = {e.get('hypothesis_id') for e in self.registry.list('experiments')}
        remaining = [h for h in self.registry.list("hypotheses") if h['id'] not in tested_ids
                     and h["experiment_type"] not in completed]
        soft_stop = decision["action"] == "stop" and decision["reason"] in {"no_improvement_patience", "hypotheses_exhausted"}
        can_llm = (self.gateway
                   and self.budget.snapshot()["experiment_count"] < self.config.budget.max_experiments
                   and state["iteration"] < self.config.research.max_iterations)
        if can_llm and (decision["action"] == "continue" and remaining or soft_stop):
            context = {"objective": self.config.objective.model_dump(), "domain": self.config.domain,
                       "review": review, "analyses": self.registry.list("analyses")[-4:],
                       "hypotheses": self.registry.list("hypotheses"),
                       "completed_experiment_types": completed,
                       "candidate_experiment_types": [h["experiment_type"] for h in remaining],
                       "budget": {"experiments_left": self.config.budget.max_experiments - self.budget.snapshot()["experiment_count"],
                                  "iterations_left": self.config.research.max_iterations - state["iteration"]}}
            try:
                routing = self.ask(f"director-{state['iteration']}",
                    "ResearchDirector: route the next step from the real review, analyses and remaining budget. Prefer an untested complementary explanation after weak evidence; stop only when no falsifiable hypothesis remains or resources are nearly exhausted. Do not invent experiment types outside candidate_experiment_types.",
                    context, RoutingDecision, complex_step=soft_stop or state["stalled"] >= 2)
            except BudgetExceeded:
                routing = None
            if routing:
                source = self.last_role(f"director-{state['iteration']}") or "model"
                if routing.action == "stop":
                    decision.update(action="stop", reason="model_decision_stop", source=source)
                elif routing.next_experiment_type in {h["experiment_type"] for h in remaining}:
                    known_reviews = {r["id"] for r in self.registry.list("reviews")}
                    decision.update(action="continue", next_template=routing.next_experiment_type,
                                    reason=routing.reason,
                                    evidence_ids=[e for e in routing.evidence_ids if e in known_reviews],
                                    source=source)
        if can_llm and decision["action"] == "stop" and not remaining and decision["reason"] in {"hypotheses_exhausted", "model_decision_stop"}:
            # Before giving up, let the model propose new hypotheses (and register tools) from the accumulated evidence.
            try:
                profile = self.registry.get("profile")
                context = {"objective": self.config.objective.model_dump(), "domain": self.config.domain,
                           "profile": profile,
                           "reviews": self.registry.list("reviews")[-8:],
                           "hypotheses": self.registry.list("hypotheses"),
                           "tools": {name: {"purpose": spec["purpose"], "custom": spec.get("custom", False),
                                            "example": spec.get("example")}
                                     for name, spec in self.tools.items()},
                           "base_observations": [profile["id"], *[r["id"] for r in self.registry.list("reviews")[-3:]]],
                           "max_hypotheses": self.config.research.max_hypotheses}
                created, _ = self.propose_hypotheses(context, f"new-hypotheses-{state['iteration']}")
            except BudgetExceeded:
                created = []
            if created:
                for hypothesis in created:
                    self.registry.put("hypotheses", hypothesis.model_dump(), hypothesis.id)
                decision.update(action="continue", next_template=created[0].experiment_type,
                                reason="模型基于累积证据提出新假设：" + created[0].claim[:120],
                                source=self.last_role(f"new-hypotheses-{state['iteration']}") or "model")
        if state["iteration"] >= self.config.research.max_iterations:
            decision.update(action="stop", reason="iteration_limit")
        available_types = {h["experiment_type"] for h in self.registry.list("hypotheses")}
        if decision.get("next_template") not in available_types and decision["action"] != "stop":
            remaining_types = available_types - set(completed)
            if remaining_types:
                decision["next_template"] = sorted(remaining_types)[0]
            else:
                decision.update(action="stop", reason="hypotheses_exhausted")
        decision.update(id=f"decision-{state['iteration']}", experiment_id=state["current_experiment"])
        self.registry.put("decisions", decision, decision["id"])
        if decision["action"] == "continue":
            for h in self.registry.list("hypotheses"):
                if h["experiment_type"] == decision["next_template"] and review["id"] not in h["observations"]:
                    h["observations"].append(review["id"])
                    self.registry.put("hypotheses", h, h["id"])
        return ({"stop_reason": decision["reason"]} if decision["action"] == "stop" else
                {"next_template": decision["next_template"]})

    def final_evaluate(self, state):
        candidates = [e for e in self.registry.list("experiments") if not e.get("error") and e.get("metrics")]
        if not candidates:
            self.registry.put("test_skipped", {"reason": "no_valid_candidate"})
            return {}
        locked = self.registry.get("locked_candidate")
        if locked is None:
            winner = max(candidates, key=lambda e: e["metrics"]["average_precision"])
            locked = {"experiment_id": winner["experiment_id"], "model_artifact": winner["model_artifact"],
                      "validation_average_precision": winner["metrics"]["average_precision"],
                      "selection_rule": "maximum validation AP, ties resolved by experiment order"}
            self.registry.put("locked_candidate", locked)
        import shutil
        shutil.copyfile(self.root / locked["model_artifact"], self.root / "best_model.joblib")
        try:
            final = execute_isolated(self.registry, self.budget, "final-test", final_worker,
                                     {"candidate_id": locked["experiment_id"], "config": self.config.model_dump()})
        except BudgetExceeded as error:
            self.registry.put("test_skipped", {"reason": str(error)})
            return {}
        self.registry.put("test_evaluation", final)
        return {}

    def export(self, state):
        export_report(self.registry, self.config, self.budget, state)
        return {}

    def compile(self, saver):
        graph = StateGraph(ScienceState)
        nodes = [self.initialize, self.baseline, self.hypothesize, self.plan_experiment,
                 self.execute, self.review, self.decide, self.final_evaluate, self.export]
        for node in nodes:
            graph.add_node(node.__name__, node)
        graph.add_edge(START, "initialize")
        for source, target in [("initialize", "baseline"), ("baseline", "hypothesize"),
                               ("hypothesize", "plan_experiment"), ("plan_experiment", "execute"),
                               ("execute", "review"), ("review", "decide"), ("decide", "plan_experiment")]:
            graph.add_conditional_edges(source, lambda state, next_node=target: "final_evaluate" if state.get("stop_reason") else next_node,
                                        ["final_evaluate", target])
        graph.add_edge("final_evaluate", "export")
        graph.add_edge("export", END)
        return graph.compile(checkpointer=saver)

    def run(self):
        with self.registry.claim():
            return self._run()

    def _run(self):
        existing = self.registry.get("final")
        if existing is not None:
            return existing
        with SqliteSaver.from_conn_string(str(self.root / "checkpoints.sqlite")) as saver:
            graph = self.compile(saver)
            settings = {"configurable": {"thread_id": self.root.name}, "recursion_limit": 1500}
            checkpoint = graph.get_state(settings)
            try:
                result = graph.invoke(None if checkpoint.values else {}, settings) if not checkpoint.values or checkpoint.next else dict(checkpoint.values)
            except Exception as error:
                result = {**graph.get_state(settings).values, "stop_reason": "execution_error", "error": f"{type(error).__name__}: {str(error)[:500]}"}
                self.registry.put("last_error", result)
                try:
                    self.export(result)
                except Exception as export_error:
                    self.registry.put("export_error", {"error": type(export_error).__name__})
                # Leave the checkpoint resumable after a transient orchestration failure.
                return result
        self.registry.put("final", result)
        return result
