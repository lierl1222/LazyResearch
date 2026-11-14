"""Persistent HTTP adapter for the same research engine used by the CLI."""
import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field, model_validator

from .session import workflow
from .research import Task, research, append_report
from .final_report import finalize_result
from .presentation import present_events
from .results import result_markdown
from .science.budget import BudgetGovernor
from .science.gateway import ScienceGateway
from .science.registry import Registry
from .science.schemas import TaskConfig, DatasetConfig


class Submission(Task):
    previous_run_id: str | None = None
    file_ids: list[str] = Field(default_factory=list, max_length=12)
    csv_text: str = Field(default="", max_length=2_000_000)
    target: str = ""
    positive_label: str | int | float = 1
    forbidden_features: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def materials(self):
        if self.tabular_config:
            raise ValueError("网页任务请上传 CSV")
        if not (self.previous_run_id or self.sequence or self.cpu_benchmark or self.csv_text or self.domain or self.file_ids):
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

    MAX_ARCHIVE_BYTES = 1024 ** 3
    MAX_FILE_BYTES = 160 * 1024 * 1024

    async def upload_stream(self, name, blocks, *, member=False):
        name = Path(name).name
        if not name or len(name) > 160:
            raise HTTPException(422, "文件名无效")
        is_archive = not member and name.lower().endswith(".zip")
        key = uuid.uuid4().hex
        folder = self.root / "uploads" / key
        folder.mkdir(parents=True)
        size = 0
        try:
            with (folder / "content").open("wb") as out:
                async for block in blocks:
                    size += len(block)
                    if size > (self.MAX_ARCHIVE_BYTES if is_archive else self.MAX_FILE_BYTES):
                        raise HTTPException(413, "压缩包上限 1 GiB，普通文件上限 160 MiB")
                    out.write(block)
            if is_archive:
                members = []
                try:
                    with zipfile.ZipFile(folder / "content") as archive:
                        entries = [f for f in archive.infolist() if not f.is_dir()]
                        if not entries:
                            raise HTTPException(422, "ZIP 中没有文件")
                        for entry in entries:
                            async def chunks(stream):
                                while block := stream.read(262144):
                                    yield block
                            with archive.open(entry) as stream:
                                item = await self.upload_stream(Path(entry.filename).name, chunks(stream), member=True)
                                members.append({**item, "archive_path": entry.filename})
                except Exception as exc:
                    for f in members:
                        shutil.rmtree(folder.parent / f["id"])
                    if isinstance(exc, (zipfile.BadZipFile, RuntimeError, NotImplementedError)):
                        raise HTTPException(422, "ZIP 损坏、加密或压缩格式不受支持") from exc
                    raise
                meta = dict(id=key, name=name, size=size)
                (folder / "meta.json").write_text(json.dumps({**meta,"members":members}), encoding="utf8")
                return meta
            if not member and not size:
                raise HTTPException(422, "文件为空")
            meta = dict(id=key, name=name, size=size)
            (folder / "meta.json").write_text(json.dumps(meta), encoding="utf8")
            return meta
        except BaseException:
            shutil.rmtree(folder)
            raise

    def create(self, submission):
        id = uuid.uuid4().hex
        previous = self.registry(submission.previous_run_id) if submission.previous_run_id else None
        if previous and not previous.get("report"):
            raise HTTPException(409, "上一轮研究正在运行，请在结束或停止后继续")
        prior = previous.get("task") if previous else {}
        files = list(prior.get("files", []))
        attachments = list(prior.get("attachments", files))
        existing_ids = {f["id"] for f in files}
        for key in dict.fromkeys(submission.file_ids):
            if any(a["id"] == key for a in attachments):
                continue
            if not re.fullmatch(r"[a-f0-9]{32}", key):
                raise HTTPException(422, "文件引用无效")
            meta = self.root / "uploads" / key / "meta.json"
            if not meta.exists():
                raise HTTPException(422, "文件不存在")
            item = json.loads(meta.read_text(encoding="utf8"))
            members = item.pop("members", None)
            attachments.append(item)
            files.extend(members or [item])
        if len(attachments) > 12:
            raise HTTPException(422, "一个研究窗口最多继承并使用 12 个附件")
        registry = Registry(self.root / id)
        material = Task.model_validate(submission.model_dump(include=set(Task.model_fields))).model_dump()
        registry.put("conversation", {"id": self.memory(previous).root.name if previous else id,
                                      "previous_run_id": submission.previous_run_id})
        for field in ("sequence", "cpu_benchmark", "target_speedup", "seed", "domain", "tabular"):
            if field in prior and (field not in submission.model_fields_set or field == "tabular"):
                material[field] = prior[field]
        if files:
            inputs = registry.root / "inputs"
            inputs.mkdir()
            for f in files:
                source = (previous.root / "inputs" / f["id"] if f["id"] in existing_ids
                          else self.root / "uploads" / f["id"] / "content")
                shutil.copyfile(source, inputs / f["id"])
            material["attachments"] = attachments
            material["native_sources"] = any(Path(f["name"]).suffix.lower() in {".c",".cc",".cpp",".cxx"} for f in files)
            material["files"] = files
            material["favorita_files"] = {"train.csv","test.csv","sample_submission.csv"} <= {f["name"] for f in files}
            material["csv_files"] = any(f["name"].lower().endswith(".csv") for f in files)
            material["domain"] = material["domain"] or "通用研究"
        if submission.csv_text:
            path = registry.root / "input.csv"
            path.write_text(submission.csv_text, encoding="utf-8")
            material["tabular"] = TaskConfig(dataset=DatasetConfig(path=str(path.resolve()), target=submission.target,
                positive_label=submission.positive_label, forbidden_features=submission.forbidden_features)).model_dump()
        elif material.get("tabular") and previous:
            path = registry.root / "input.csv"
            shutil.copyfile(previous.root / "input.csv", path)
            material["tabular"]["dataset"]["path"] = str(path.resolve())
        registry.put("task", material)
        registry.put("state", {"status": "queued"})
        self.emit(registry, "queued", status="queued")
        return id

    def memory(self, registry):
        conversation = registry.get("conversation") or {}
        id = conversation.get("id", registry.root.name)
        return registry if id == registry.root.name else self.registry(id)

    def history(self, registry, *, limit=None):
        history = []
        previous_id = (registry.get("conversation") or {}).get("previous_run_id")
        while previous_id and (limit is None or len(history) < limit):
            previous = self.registry(previous_id)
            report = previous.get("report") or {}
            entry = {"id": previous_id, "goal": previous.get("task")["goal"], "status": report.get("status")}
            if limit is not None:
                entry["summary"] = report.get("summary", "")
                entry["evidence"] = report.get("evidence", {})
                for event in previous.get("events") or []:
                    if event["stage"] == "validation" and event.get("observation_id") and event.get("outcome"):
                        entry["evidence"].setdefault(event["observation_id"], event["outcome"])
            history.append(entry)
            previous_id = (previous.get("conversation") or {}).get("previous_run_id")
        return list(reversed(history))

    def recent_research(self, registry):
        history = self.history(registry, limit=2)
        for entry in history:
            entry["goal"] = entry["goal"][:600]
            entry["summary"] = entry["summary"][:800]
            entry["evidence"] = [
                {"id": key, "observation": json.dumps(
                    {k: v for k, v in value.items()
                     if k not in {"config_hash", "data_hash", "cpu_seconds", "elapsed_seconds",
                                  "wall_seconds", "run_id", "experiment_id", "baseline_ns", "candidate_ns"}},
                    ensure_ascii=False)[:480]}
                for key, value in list(entry["evidence"].items())[-5:]
            ]
        return history

    def emit(self, registry, stage, **details):
        with registry.transaction() as db:
            events = registry.get_from(db, "events", "current") or []
            events.append({"id": len(events) + 1, "stage": stage, **details})
            registry.put_into(db, "events", "current", events)
            material = registry.get_from(db, "task", "current") or {}
        files = material.get("files", [])
        display = present_events(events, files)[-1]["display"] if stage == "plan" else None
        append_report(registry.root, stage, details, files=files, display=display)

    def run(self, id):
        registry = self.registry(id)
        with registry.claim():
            if registry.get("report"):
                return
            material = registry.get("task")
            task = Task.model_validate({k: v for k, v in material.items() if k in Task.model_fields})
            registry.put("state", {"status": "running"})
            self.emit(registry, "running", status="running")
            budget = BudgetGovernor(registry, task.budget)
            gateway = self.gateway_factory(self.config, registry, budget, allow_reporting=True)
            try:
                report = research(task, material, registry, gateway, budget,
                    lambda stage, **details: self.emit(registry, stage, **details),
                    previous_research=self.recent_research(registry), memory=self.memory(registry))
            except Exception as error:
                report = {"status": "failed", "summary": type(error).__name__, "evidence": {},
                          "delegations": [], "budget": budget.snapshot()}
            try:
                finalize_result(registry, report, gateway, budget,
                                memory=self.memory(registry), previous_research=self.recent_research(registry),
                                emit=lambda stage, **details: self.emit(registry, stage, **details))
            except Exception:
                result_markdown(registry, report, save=True)
            report["budget"] = budget.snapshot()
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
                result_markdown(registry, report, save=True)
                self.emit(registry, "finished", status="stopped", summary=report["summary"])

    def snapshot(self, id):
        registry = self.registry(id)
        task = registry.get("task")
        report = registry.get("report")
        budget = report.get("budget", {}) if report else {}
        if registry.get("budget"):
            budget = BudgetGovernor(registry, Task.model_validate({k:v for k,v in task.items() if k in Task.model_fields}).budget).snapshot()
        usage = {role: {"calls": 0, "output_tokens": 0} for role in ("cloud", "local")}
        operations = budget.get("operations", {})
        legacy_roles = {}
        if any(op["kind"] == "llm" and not op.get("role") for op in operations.values()):
            legacy_roles = {call["id"]: call.get("role") for call in registry.list("model_calls")}
        for key, op in operations.items():
            if op["kind"] != "llm":
                continue
            role = op.get("role") or legacy_roles.get(key)
            if role in usage:
                usage[role]["calls"] += 1
                usage[role]["output_tokens"] += op["output_tokens"]
        unknown = {"calls": budget.get("llm_calls", 0) - sum(v["calls"] for v in usage.values()),
                   "output_tokens": budget.get("output_tokens", 0) - sum(v["output_tokens"] for v in usage.values())}
        if any(unknown.values()):
            usage["unknown"] = unknown
        budget["by_model"] = usage
        budget["cloud_requests"] = usage["cloud"]["calls"]
        events = registry.get("events") or []
        events = present_events(events, task.get("files", []))
        memory = self.memory(registry)
        status = report["status"] if report else registry.get("state")["status"]
        if report and report.get("budget") and "discussions" not in (registry.get("budget") or {}):
            budget["wall_seconds"] = report["budget"]["wall_seconds"]
        return {"id": id, "conversation_id": memory.root.name, "result": result_markdown(registry, report), "workflow": workflow(events, status),
                "research_history": self.history(registry), "exchanges": memory.list("exchanges"), "task": task, "status": status,
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
            native = registry.root / "topk" / "LLM_TopK_Agent_Benchmark"
            for trial in (native/"results").glob("partition-*.json"):
                archive.write(trial,"topk/results/"+trial.name)
            for rel in ("src/candidate.hpp","results/initial.json","results/candidate.json","results/final.json"):
                if (native / rel).is_file():
                    archive.write(native / rel, "topk/" + rel)
            for artifact in (registry.root/"native-result").glob("*"):
                if artifact.is_file():
                    archive.write(artifact,"native-result/"+artifact.name)
            archive.writestr("result.md", result_markdown(registry, registry.get("report")))
            for name in ("submission.csv","benchmark.json"):
                if (registry.root / name).is_file():
                    archive.write(registry.root / name, name)
            archive.writestr("memory.json", json.dumps(self.memory(registry).list("exchanges"), ensure_ascii=False))
            for f in registry.get("task").get("files", []):
                archive.write(registry.root / "inputs" / f["id"], "inputs/" + f["id"] + "/" + f["name"])
            for path in (registry.root / "workers").glob("*.json"):
                archive.write(path, "workers/" + path.name)
            if (registry.root / "report.md").exists():
                archive.write(registry.root / "report.md", "report.md")
            if (registry.root / "input.csv").exists():
                archive.write(registry.root / "input.csv", "input.csv")
        return stream.getvalue()
