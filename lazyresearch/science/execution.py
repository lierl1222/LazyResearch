"""Spawn-only scientific workers with bounded time and durable outcome files."""
import hashlib
import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

from .budget import BudgetGovernor
from .registry import Registry


def _child(root, id, worker, payload, allowance, parent_alive):
    def watchdog():
        while True:
            if time.process_time() >= allowance:
                os._exit(124)
            if parent_alive.poll(.03):
                try:
                    parent_alive.recv()
                except EOFError:
                    os._exit(125)
    threading.Thread(target=watchdog, daemon=True).start()
    started = time.perf_counter()
    try:
        value = worker(Path(root), payload)
    except Exception as error:
        value = {"error": f"{type(error).__name__}: {str(error)[:500]}"}
    value.update(cpu_seconds=time.process_time(), elapsed_seconds=time.perf_counter() - started)
    path = Path(root) / "workers" / f"{id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def execute_isolated(registry: Registry, budget: BudgetGovernor, id: str, worker, payload: dict, *, kind="experiment") -> dict:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", id):
        raise ValueError("Invalid operation ID")
    existing = registry.get("executions", id)
    if existing is not None:
        return existing
    folder = registry.root / "workers"
    folder.mkdir(exist_ok=True)
    path = folder / f"{id}.json"
    operation = budget.snapshot()["operations"].get(id)
    if operation:
        # Never rerun an uncertain operation after a crash, especially final test evaluation.
        result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"error": "interrupted_execution_not_repeated"}
        budget.settle_experiment(id, result.get("cpu_seconds"))
    else:
        allowance = budget.reserve_experiment(id, kind=kind)
        ctx = multiprocessing.get_context("spawn")
        read_end, write_end = ctx.Pipe(duplex=False)
        previous = {key: os.environ.get(key) for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
        for key in previous:
            os.environ[key] = "1"
        process = ctx.Process(target=_child, args=(str(registry.root), id, worker, payload, allowance, read_end))
        started = time.perf_counter()
        try:
            process.start()
            read_end.close()
            while process.is_alive() and time.perf_counter() - started < allowance and not (registry.root / "stop.requested").exists():
                process.join(min(.05, max(.001, allowance - (time.perf_counter() - started))))
            if process.is_alive():
                process.terminate()
                process.join(3)
                if process.is_alive():
                    process.kill()
                    process.join()
                result = {"error": "user_stop" if (registry.root / "stop.requested").exists() else "experiment_timeout"}
            elif path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
            else:
                result = {"error": "cpu_budget" if process.exitcode == 124 else f"worker_exit_{process.exitcode}"}
            result["wall_seconds"] = time.perf_counter() - started
            budget.settle_experiment(id, result.get("cpu_seconds"))
        finally:
            write_end.close()
            read_end.close()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    result.update(run_id=registry.root.name, experiment_id=id,
                  config_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
    registry.put("executions", result, id)
    return result
