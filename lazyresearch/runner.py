import io
import json
import time
import uuid
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from langgraph.checkpoint.sqlite import SqliteSaver

from .adapters import FixtureAdapter, ResearchAdapter
from .model_gateway import ModelGateway, Prompts
from .models import ResearchTask, Result, Revision, Validation
from .storage import Storage
from .workflow import Workflow


class Runner:
    def __init__(self, root: Path, adapters: dict[str, ResearchAdapter] | None = None,
                 prompts: Prompts | None = None, gateway: ModelGateway | None = None):
        self.root = root
        self.storage = Storage(root)
        self.adapters = {"fixture": FixtureAdapter()} if adapters is None else adapters
        self.prompts = prompts or Prompts()
        self.gateway = gateway

    @property
    def mode(self):
        return "gateway_ready" if self.gateway and (self.prompts.planning or self.prompts.diagnosis) else "local"

    def create(self, task: ResearchTask) -> str:
        if task.adapter_id not in self.adapters:
            raise ValueError("未知适配器")
        self.adapters[task.adapter_id].validate(task)
        run_id = uuid.uuid4().hex
        self.storage.put(run_id, "task", task.model_dump())
        self.storage.emit(run_id, "queued", status="queued")
        return run_id

    def run(self, run_id: str) -> dict:
        if self.storage.get(run_id, "task") is None:
            raise KeyError(run_id)
        with self.storage.claim(run_id):
            return self._run(run_id)

    def _run(self, run_id: str) -> dict:
        stored_task = self.storage.get(run_id, "task")
        if stored_task is None:
            raise KeyError(run_id)
        final = self.storage.get(run_id, "final")
        if final is None:
            task = ResearchTask.model_validate(stored_task)
            if task.adapter_id not in self.adapters:
                final = {"run_id": run_id, "task": stored_task, "stop_reason": "execution_error",
                         "error": f"适配器未注册：{task.adapter_id}", "status": "failed",
                         "cloud_requests": 0, "tokens": 0, "tokens_pending": 0, "elapsed": 0}
                self.storage.finish(run_id, final)
                return {**final, "results": [], "revisions": [], "validation": None}
            started = self.storage.get(run_id, "started")
            if started is None:
                started = time.time()
                self.storage.put(run_id, "started", started)
            deadline = started + task.budget.seconds
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 1500,
                      "max_concurrency": 2}
            self.storage.emit(run_id, "running", status="running")
            workflow = Workflow(self.adapters[task.adapter_id], self.storage, self.prompts, self.gateway)
            with SqliteSaver.from_conn_string(str(self.root / "checkpoints.sqlite")) as saver:
                graph = workflow.compile(saver)
                checkpoint = graph.get_state(config)
                initial = {"run_id": run_id, "deadline": deadline, "task": stored_task}
                error_message = None
                try:
                    if not checkpoint.values:
                        final = graph.invoke(initial, config)
                    elif checkpoint.next:
                        final = graph.invoke(None, config)
                    else:
                        final = checkpoint.values
                except Exception as error:
                    final = graph.get_state(config).values or initial
                    final["stop_reason"] = "execution_error"
                    error_message = f"{type(error).__name__}: {str(error)[:400]}"
            final = {key: value for key, value in final.items() if key not in {"batch", "queue", "deadline"}}
            final.update(workflow.cloud_ledger(run_id), elapsed=round(time.time() - started, 3),
                         status="failed" if error_message else "finished")
            if error_message:
                final["error"] = error_message
            self.storage.finish(run_id, final)
        return {**final,
                "results": [Result.model_validate(row) for row in final.get("results", [])],
                "revisions": [Revision.model_validate(row) for row in final.get("revisions", [])],
                "validation": Validation.model_validate(final["validation"]) if "validation" in final else None}

    def snapshot(self, run_id: str) -> dict:
        task = self.storage.get(run_id, "task")
        if task is None:
            raise KeyError(run_id)
        final = self.storage.get(run_id, "final")
        started = self.storage.get(run_id, "started")
        return {"id": run_id, "task": task, "mode": self.mode,
                "status": "running" if started is not None else "queued",
                "elapsed": time.time() - started if started is not None else 0,
                **(final or {})}

    def artifacts(self, run_id: str) -> bytes:
        state = self.storage.get(run_id, "final")
        if state is None:
            raise ValueError("任务尚未结束")
        payload = io.BytesIO()
        with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
            task = state["task"]
            archive.writestr("task.json", self.encode(task))
            archive.writestr("run.json", self.encode(state))
            archive.writestr("events.json", self.encode(self.storage.events(run_id)))
            archive.writestr("evidence.json", self.encode(state.get("evidence", [])))
            for result in state.get("results", []):
                archive.writestr(result["artifact"], self.encode(result))
            validation = state.get("validation", {}).get("summary", "无验证结论")
            archive.writestr("report.md", "\n".join([
                "# 研究报告", "", task["goal"], "", f"- 停止原因：{state['stop_reason']}",
                f"- 验证：{validation}", f"- 轮次：{state.get('round', 0)}",
                f"- 工具次数：{state.get('tools', 0)}", f"- 已确认 token：{state['tokens']}",
                f"- 待确认 token：{state['tokens_pending']}", f"- 耗时：{state['elapsed']} 秒",
                "", "复跑：`python -m lazyresearch --task task.json`", "",
            ]))
        return payload.getvalue()

    @staticmethod
    def encode(value) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)
