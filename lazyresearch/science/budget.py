import time

from .registry import Registry
from .schemas import ScienceBudget


class BudgetExceeded(RuntimeError):
    pass


class BudgetGovernor:
    def __init__(self, registry: Registry, limits: ScienceBudget, *, enforce_llm_limits=False):
        self.registry, self.limits = registry, limits
        self.enforce_llm_limits = enforce_llm_limits
        with registry.transaction() as db:
            if registry.get_from(db, "budget", "current") is None:
                registry.put_into(db, "budget", "current", {"started": time.time(), "operations": {}})

    def snapshot(self):
        return self._snapshot(self.registry.get("budget"))

    def _snapshot(self, ledger):
        ops = list(ledger["operations"].values())
        calls = [o for o in ops if o["kind"] == "llm"]
        experiments = [o for o in ops if o["kind"] == "experiment"]
        compute = [o for o in ops if o["kind"] in {"experiment", "compute"}]
        return {
            "input_tokens": sum(o["input_tokens"] for o in calls),
            "output_tokens": sum(o["output_tokens"] for o in calls),
            "llm_calls": len(calls), "experiment_count": len(experiments),
            "cpu_seconds": sum(o["cpu_seconds"] for o in compute),
            "wall_seconds": time.time() - ledger["started"],
            "unknown_usage_calls": sum(o.get("usage_status") != "actual" for o in calls),
            "api_cost_usd": sum(o["cost_usd"] for o in calls) if calls and all(o.get("cost_usd") is not None for o in calls) else (0 if not calls else None),
            "operations": ledger["operations"], "limits": self.limits.model_dump(),
        }

    def remaining_time(self):
        return max(0, self.limits.max_wall_time_seconds - self.snapshot()["wall_seconds"])

    def _check_time(self, snapshot, *, allow_reporting=False):
        if (self.registry.root / "stop.requested").exists():
            raise BudgetExceeded("user_stop")
        if snapshot["wall_seconds"] >= self.limits.max_wall_time_seconds:
            raise BudgetExceeded("wall_time_budget")
        if not allow_reporting and snapshot["cpu_seconds"] >= self.limits.max_cpu_seconds:
            raise BudgetExceeded("cpu_budget")
        if not allow_reporting and snapshot["experiment_count"] >= self.limits.max_experiments:
            raise BudgetExceeded("experiment_budget")
        if self.enforce_llm_limits:
            if snapshot["llm_calls"] >= self.limits.max_llm_calls:
                raise BudgetExceeded("llm_call_budget")
            if snapshot["input_tokens"] >= self.limits.max_llm_input_tokens or snapshot["output_tokens"] >= self.limits.max_llm_output_tokens:
                raise BudgetExceeded("token_budget")
            cap = self.limits.max_api_cost_usd
            if cap is not None and snapshot["api_cost_usd"] is not None and snapshot["api_cost_usd"] >= cap:
                raise BudgetExceeded("cost_budget")

    def reserve_experiment(self, id, *, kind="experiment"):
        with self.registry.transaction() as db:
            ledger = self.registry.get_from(db, "budget", "current")
            if id in ledger["operations"]:
                raise BudgetExceeded("operation_already_reserved")
            snapshot = self._snapshot(ledger)
            self._check_time(snapshot)
            if kind == "experiment" and snapshot["experiment_count"] >= self.limits.max_experiments:
                raise BudgetExceeded("experiment_budget")
            remaining_cpu = self.limits.max_cpu_seconds - snapshot["cpu_seconds"]
            allowance = min(remaining_cpu, self.limits.max_single_experiment_seconds,
                            self.limits.max_wall_time_seconds - snapshot["wall_seconds"])
            if allowance <= 0:
                raise BudgetExceeded("cpu_budget")
            ledger["operations"][id] = {"kind": kind, "status": "reserved",
                                        "cpu_seconds": allowance, "allowance_seconds": allowance}
            self.registry.put_into(db, "budget", "current", ledger)
            return allowance

    def settle_experiment(self, id, cpu_seconds: float | None):
        with self.registry.transaction() as db:
            ledger = self.registry.get_from(db, "budget", "current")
            op = ledger["operations"][id]
            if op["status"] == "settled":
                return
            if cpu_seconds is not None:
                op["cpu_seconds"] = max(0, cpu_seconds)
            op.update(status="settled", cpu_status="measured" if cpu_seconds is not None else "reserved_unknown")
            self.registry.put_into(db, "budget", "current", ledger)

    def reserve_llm(self, id, input_tokens, output_tokens, cost_usd=None, *, allow_reporting=False):
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Negative token reservation")
        with self.registry.transaction() as db:
            ledger = self.registry.get_from(db, "budget", "current")
            if id in ledger["operations"]:
                raise BudgetExceeded("operation_already_reserved")
            s = self._snapshot(ledger)
            self._check_time(s, allow_reporting=allow_reporting)
            if s["llm_calls"] >= self.limits.max_llm_calls:
                raise BudgetExceeded("llm_call_budget")
            if s["input_tokens"] + input_tokens > self.limits.max_llm_input_tokens or s["output_tokens"] + output_tokens > self.limits.max_llm_output_tokens:
                raise BudgetExceeded("token_budget")
            cap = self.limits.max_api_cost_usd
            if cap is not None and (cost_usd is None or s["api_cost_usd"] is None or s["api_cost_usd"] + cost_usd > cap):
                raise BudgetExceeded("cost_budget_or_unknown_pricing")
            ledger["operations"][id] = {"kind": "llm", "status": "reserved", "input_tokens": input_tokens,
                                        "output_tokens": output_tokens, "usage_status": "reserved_unknown", "cost_usd": cost_usd}
            self.registry.put_into(db, "budget", "current", ledger)

    def settle_llm(self, id, input_tokens, output_tokens, cost_usd=None):
        with self.registry.transaction() as db:
            ledger = self.registry.get_from(db, "budget", "current")
            op = ledger["operations"][id]
            if op["status"] == "settled":
                return
            actual = type(input_tokens) is int and input_tokens >= 0 and type(output_tokens) is int and output_tokens >= 0
            if actual:
                op.update(input_tokens=input_tokens, output_tokens=output_tokens)
            op.update(status="settled", usage_status="actual" if actual else "reserved_unknown", cost_usd=cost_usd)
            self.registry.put_into(db, "budget", "current", ledger)
