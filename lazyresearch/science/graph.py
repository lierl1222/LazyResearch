import hashlib
import json
from pathlib import Path
from typing import TypedDict

import joblib
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .agents import AlgorithmEngineer, DataScientist, HypothesisScientist, HypothesisSpec, ResearchDirector, ScientificReviewer
from .budget import BudgetExceeded, BudgetGovernor
from .execution import execute_isolated
from .experiments import ExperimentSpec, run_experiment
from .registry import Registry
from .schemas import TaskConfig
from .gateway import ScienceGateway, ResearchPlan, Selection
from ..configuration import load_model_config
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


class ScienceState(TypedDict, total=False):
    iteration: int
    completed_templates: list[str]
    next_template: str
    current_hypothesis: str
    current_experiment: str
    stalled: int
    stop_reason: str
    error: str


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
        if config.llm.provider == "configured_api":
            model_config = (model_config or load_model_config()).model_copy(deep=True)
            if config.llm.model:
                model_config.cloud.model = config.llm.model
            self.gateway = ScienceGateway(model_config, self.registry, self.budget)
        else:
            self.gateway = None

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

    def _execute(self, spec, baseline=None):
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
            hypotheses = HypothesisScientist().propose(self.registry.get("profile"))
            if self.registry.get("experiments", "baseline-logistic"):
                for hypothesis in hypotheses:
                    hypothesis.observations.append("baseline-logistic")
            if not self.config.research.allow_advanced_models:
                hypotheses = [h for h in hypotheses if h.experiment_type != "nonlinear_model"]
            if self.gateway:
                try:
                    if self.budget.snapshot()["experiment_count"] >= self.config.budget.max_experiments:
                        raise BudgetExceeded("experiment_budget")
                    plan = self.gateway.ask("cloud", "research-plan", "ResearchDirector: select and prioritize distinct executable hypothesis cards from the supplied hypotheses. Return hypothesis_ids using their exact IDs. Do not invent methods, edit claims, or quote evidence prose as IDs. The plan summary explains evidence-based priority; all tests and falsification rules are defined by the cards.",
                                            {"objective": self.config.objective.model_dump(), "profile": self.registry.get("profile"),
                                             "baselines": [{"id": e["experiment_id"], "metrics": e.get("metrics")} for e in self.registry.list("experiments")],
                                             "hypotheses": [h.model_dump() for h in hypotheses],
                                             "max_hypotheses": self.config.research.max_hypotheses}, ResearchPlan)
                    available = {h.id: h for h in hypotheses}
                    if len(set(plan.hypothesis_ids)) != len(plan.hypothesis_ids) or not set(plan.hypothesis_ids) <= set(available):
                        raise ValueError("Invalid or duplicate hypothesis IDs")
                    hypotheses = [available[id] for id in plan.hypothesis_ids]
                    self.registry.put("research_plan", plan.model_dump())
                except BudgetExceeded as error:
                    return {"stop_reason": str(error)}
                except (RuntimeError, ValueError) as error:
                    if not self.config.llm.allow_mock:
                        return {"stop_reason": "model_planning_failed"}
                    self.registry.put("fallback", {"mode": "mock_fallback", "reason": type(error).__name__})
            for hypothesis in hypotheses[:self.config.research.max_hypotheses]:
                self.registry.put("hypotheses", hypothesis.model_dump(), hypothesis.id)
        first = self.registry.list("hypotheses")[0]
        return {"next_template": first["experiment_type"]}

    def plan_experiment(self, state):
        available = self.registry.list("hypotheses")
        hypothesis = next((h for h in available if h["experiment_type"] == state["next_template"]), None)
        if hypothesis is None:
            return {"stop_reason": "hypotheses_exhausted"}
        hypothesis = HypothesisSpec.model_validate(hypothesis)
        spec = AlgorithmEngineer().plan(hypothesis, f"experiment-{state['iteration'] + 1}",
                                       self.registry.get("profile")["features"], self.config.validation.random_seed,
                                       min(3600, self.config.budget.max_single_experiment_seconds))
        self.registry.put("plans", spec.model_dump(), spec.id)
        return {"current_hypothesis": hypothesis.id, "current_experiment": spec.id}

    def execute(self, state):
        spec = ExperimentSpec.model_validate(self.registry.get("plans", state["current_experiment"]))
        try:
            self._execute(spec, self.registry.get("experiments", "baseline-logistic"))
        except BudgetExceeded as error:
            return {"stop_reason": str(error)}
        return {"iteration": state["iteration"] + 1,
                "completed_templates": state["completed_templates"] + [spec.experiment_type]}

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
        return {"stalled": 0 if review["verdict"] == "accept" else state["stalled"] + 1}

    def decide(self, state):
        review = self.registry.get("reviews", f"review-{state['current_experiment']}")
        decision = self.director.decide(review, state["completed_templates"], state["stalled"],
                                        self.config.research.no_improvement_patience)
        if decision.get("reason") == "no_improvement_patience" and len(self.registry.list("experiments")) < self.config.research.min_required_experiments:
            decision = self.director.decide(review, state["completed_templates"], 0,
                                            self.config.research.no_improvement_patience)
            decision["reason"] = "Continue toward minimum experiments while budget and hypotheses permit."
        if state["iteration"] >= self.config.research.max_iterations:
            decision.update(action="stop", reason="iteration_limit")
        if self.budget.snapshot()["experiment_count"] >= self.config.budget.max_experiments - 1:
            decision.update(action="stop", reason="reserve_final_evaluation")
        current_result = self.registry.get("experiments", state["current_experiment"])
        target = self.config.objective.target_score
        if target is not None and review["verdict"] == "accept" and current_result.get("metrics", {}).get("average_precision", 0) >= target:
            decision.update(action="stop", reason="validation_target_reached")
        remaining_hypotheses = [h for h in self.registry.list("hypotheses") if h["experiment_type"] not in state["completed_templates"]]
        if self.gateway and decision["action"] == "continue" and remaining_hypotheses and self.budget.snapshot()["experiment_count"] < self.config.budget.max_experiments:
            role = "cloud" if state["stalled"] >= 2 else "local"
            try:
                selection = self.gateway.ask(role, f"selection-{state['iteration']}",
                                             "Select one available hypothesis using the real review and remaining budget.",
                                             {"review": review, "available": remaining_hypotheses}, Selection)
                chosen = next((h for h in remaining_hypotheses if h["id"] == selection.hypothesis_id), None)
                if chosen is None:
                    raise ValueError("Unknown hypothesis selected")
                decision.update(next_template=chosen["experiment_type"], reason=selection.reason, source=role)
            except (BudgetExceeded, RuntimeError, ValueError) as error:
                decision.update(source="deterministic_fallback", model_failure=type(error).__name__)
        if state["iteration"] >= self.config.research.max_iterations:
            decision.update(action="stop", reason="iteration_limit")
        available = {h["experiment_type"] for h in self.registry.list("hypotheses")}
        if decision.get("next_template") not in available and decision["action"] != "stop":
            remaining = available - set(state["completed_templates"])
            if remaining:
                decision["next_template"] = sorted(remaining)[0]
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
