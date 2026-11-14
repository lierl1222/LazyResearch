"""Persistent HTTP adapter for the same research engine used by the CLI."""
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field, model_validator

from .research import Task, research, append_report
from .science.budget import BudgetGovernor
from .science.gateway import ScienceGateway
from .science.registry import Registry
from .science.schemas import TaskConfig, DatasetConfig


class Submission(Task):
    csv_text: str = Field(default="", max_length=2_000_000)
    target: str = ""
    positive_label: str | int | float = 1
    forbidden_features: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def materials(self):
        if self.tabular_config:
            raise ValueError("网页任务请上传 CSV")
        if not (self.sequence or self.cpu_benchmark or self.csv_text):
            raise ValueError("请提供数列、CPU 基准或 CSV 数据")
        if self.csv_text and not self.target:
            raise ValueError("CSV 研究需要指定目标列")
        return self


class ResearchService:
    def __init__(self, root, config, gateway_factory=ScienceGateway):
        self.root, self.config = Path(root), config
        self.root.mkdir(parents=True, exist_ok=True)
        self.gateway_factory = gateway_factory

    def registry(self, id):
        if not re.fullmatch(r"[a-f0-9]{32}", id) or not (self.root / id / "registry.sqlite").exists():
            raise HTTPException(404, "研究任务不存在")
        return Registry(self.root / id)

    def create(self, submission):
        id = uuid.uuid4().hex
        registry = Registry(self.root / id)
        material = Task.model_validate(submission.model_dump(exclude={"csv_text", "target", "positive_label", "forbidden_features"})).model_dump()
        if submission.csv_text:
            path = registry.root / "input.csv"
            path.write_text(submission.csv_text, encoding="utf-8")
            material["tabular"] = TaskConfig(dataset=DatasetConfig(path=str(path.resolve()), target=submission.target,
                positive_label=submission.positive_label, forbidden_features=submission.forbidden_features)).model_dump()
        registry.put("task", material)
        registry.put("state", {"status": "queued"})
        self.emit(registry, "queued", status="queued")
        return id

    def emit(self, registry, stage, **details):
        with registry.transaction() as db:
            events = registry.get_from(db, "events", "current") or []
            events.append({"id": len(events) + 1, "stage": stage, **details})
            registry.put_into(db, "events", "current", events)
        append_report(registry.root, stage, details)

    def run(self, id):
        registry = self.registry(id)
        with registry.claim():
            if registry.get("report"):
                return
            material = registry.get("task")
            task = Task.model_validate({k: v for k, v in material.items() if k != "tabular"})
            registry.put("state", {"status": "running"})
            self.emit(registry, "running", status="running")
            budget = BudgetGovernor(registry, task.budget)
            try:
                report = research(task, material, registry,
                    self.gateway_factory(self.config, registry, budget, allow_reporting=True), budget,
                    lambda stage, **details: self.emit(registry, stage, **details))
            except Exception as error:
                report = {"status": "failed", "summary": type(error).__name__, "evidence": {},
                          "delegations": [], "budget": budget.snapshot()}
            registry.put("report", report)
            registry.put("state", {"status": report["status"]})
            self.emit(registry, "finished", status=report["status"], summary=report["summary"])

    def recover(self):
        for folder in self.root.iterdir():
            if not folder.is_dir() or not (folder / "registry.sqlite").exists():
                continue
            registry = Registry(folder)
            if registry.get("report"):
                continue
            state = registry.get("state") or {}
            if state.get("status") == "queued":
                yield folder.name
            else:
                report = {"status": "stopped", "summary": "服务重启导致任务中断，请创建新任务。", "evidence": {},
                          "delegations": []}
                registry.put("report", report)
                self.emit(registry, "finished", status="stopped", summary=report["summary"])

    def snapshot(self, id):
        registry = self.registry(id)
        task = registry.get("task")
        report = registry.get("report")
        budget = report.get("budget", {}) if report else {}
        if not budget and registry.get("budget"):
            budget = BudgetGovernor(registry, Task.model_validate({k:v for k,v in task.items() if k != "tabular"}).budget).snapshot()
        events = registry.get("events") or []
        return {"id": id, "task": task, "status": report["status"] if report else registry.get("state")["status"],
                "elapsed": budget.get("wall_seconds", 0), "budget": budget, "events": events, "report": report}

    def bundle(self, id):
        registry = self.registry(id)
        if not registry.get("report"):
            raise HTTPException(409, "任务结束后可下载研究包")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in (("task.json", registry.get("task")), ("report.json", registry.get("report")),
                                ("events.json", registry.get("events")), ("model_calls.json", registry.list("model_calls"))):
                archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
            for path in (registry.root / "workers").glob("*.json"):
                archive.write(path, "workers/" + path.name)
            if (registry.root / "report.md").exists():
                archive.write(registry.root / "report.md", "report.md")
            if (registry.root / "input.csv").exists():
                archive.write(registry.root / "input.csv", "input.csv")
        return stream.getvalue()
