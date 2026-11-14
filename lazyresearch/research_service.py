"""Persistent HTTP adapter for the same research engine used by the CLI."""
import codecs
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
from .results import result_markdown
from .science.budget import BudgetGovernor
from .science.gateway import ScienceGateway
from .science.registry import Registry
from .science.schemas import TaskConfig, DatasetConfig


class Submission(Task):
    file_ids: list[str] = Field(default_factory=list, max_length=12)
    csv_text: str = Field(default="", max_length=2_000_000)
    target: str = ""
    positive_label: str | int | float = 1
    forbidden_features: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def materials(self):
        if self.tabular_config:
            raise ValueError("网页任务请上传 CSV")
        if not (self.sequence or self.cpu_benchmark or self.csv_text or self.domain or self.file_ids):
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

    MAX_FILE_BYTES = 160 * 1024 * 1024

    async def upload_stream(self, name, blocks):
        name = Path(name).name
        if not name or len(name)>160 or Path(name).suffix.lower() not in {".csv",".txt",".md",".json",".tsv",".zip"}:
            raise HTTPException(422, "支持 UTF-8 CSV、TSV、TXT、MD、JSON 文件及其 ZIP 压缩包")
        key = uuid.uuid4().hex
        folder = self.root / "uploads" / key
        folder.mkdir(parents=True)
        size = 0
        nonempty = False
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        try:
            with (folder / "content").open("wb") as out:
                async for block in blocks:
                    size += len(block)
                    if size > self.MAX_FILE_BYTES:
                        raise HTTPException(413, "单文件上限 160 MiB")
                    if name.lower().endswith(".zip"):
                        out.write(block)
                        continue
                    text = decoder.decode(block)
                    if chr(0) in text:
                        raise HTTPException(422, "文件包含二进制内容")
                    nonempty = nonempty or bool(text.strip())
                    out.write(block)
                decoder.decode(b"", final=True)
            if name.lower().endswith(".zip"):
                members = []
                try:
                    with zipfile.ZipFile(folder / "content") as archive:
                        entries = [f for f in archive.infolist() if not f.is_dir()]
                        if not 1 <= len(entries) <= 12 or sum(f.file_size for f in entries) > 2*self.MAX_FILE_BYTES:
                            raise HTTPException(422, "ZIP 最多包含 12 个文件，解压总量上限 320 MiB")
                        for entry in entries:
                            if Path(entry.filename).suffix.lower() not in {".csv",".txt",".md",".json",".tsv"}:
                                raise HTTPException(422, "ZIP 中包含不支持的文件类型")
                            async def chunks(stream):
                                while block := stream.read(262144):
                                    yield block
                            with archive.open(entry) as stream:
                                members.append(await self.upload_stream(Path(entry.filename).name, chunks(stream)))
                except Exception as exc:
                    for f in members:
                        shutil.rmtree(folder.parent / f["id"])
                    if isinstance(exc, (zipfile.BadZipFile, RuntimeError, NotImplementedError)):
                        raise HTTPException(422, "ZIP 损坏、加密或压缩格式不受支持") from exc
                    raise
                shutil.rmtree(folder)
                return {"name": name, "files": members}
            if not nonempty:
                raise HTTPException(422, "文件为空")
            meta = dict(id=key, name=name, size=size)
            (folder / "meta.json").write_text(json.dumps(meta), encoding="utf8")
            return meta
        except BaseException as error:
            shutil.rmtree(folder)
            if isinstance(error, UnicodeDecodeError):
                raise HTTPException(422, "文件需要使用 UTF-8 编码") from error
            raise

    def create(self, submission):
        id = uuid.uuid4().hex
        files = []
        for key in dict.fromkeys(submission.file_ids):
            if not re.fullmatch(r"[a-f0-9]{32}", key):
                raise HTTPException(422, "文件引用无效")
            meta = self.root / "uploads" / key / "meta.json"
            if not meta.exists():
                raise HTTPException(422, "文件不存在")
            files.append(json.loads(meta.read_text(encoding="utf8")))
        registry = Registry(self.root / id)
        material = Task.model_validate(submission.model_dump(exclude={"file_ids", "csv_text", "target", "positive_label", "forbidden_features"})).model_dump()
        if files:
            inputs = registry.root / "inputs"
            inputs.mkdir()
            for f in files:
                shutil.copyfile(self.root / "uploads" / f["id"] / "content", inputs / f["id"])
            material["files"] = files
            material["favorita_files"] = {"train.csv","test.csv","sample_submission.csv"} <= {f["name"] for f in files}
            material["csv_files"] = any(f["name"].lower().endswith(".csv") for f in files)
            material["domain"] = material["domain"] or "通用研究"
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
            task = Task.model_validate({k: v for k, v in material.items() if k in Task.model_fields})
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
            result_markdown(registry, report)
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
                result_markdown(registry, report)
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
        status = report["status"] if report else registry.get("state")["status"]
        if report and report.get("budget") and "discussions" not in (registry.get("budget") or {}):
            budget["wall_seconds"] = report["budget"]["wall_seconds"]
        return {"id": id, "conversation_id": id, "result": result_markdown(registry, report), "workflow": workflow(events, status),
                "exchanges": registry.list("exchanges"), "task": task, "status": report["status"] if report else registry.get("state")["status"],
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
            archive.writestr("result.md", result_markdown(registry, registry.get("report")))
            for name in ("submission.csv","benchmark.json"):
                if (registry.root / name).is_file():
                    archive.write(registry.root / name, name)
            archive.writestr("memory.json", json.dumps(registry.list("exchanges"), ensure_ascii=False))
            for f in registry.get("task").get("files", []):
                archive.write(registry.root / "inputs" / f["id"], "inputs/" + f["id"] + "/" + f["name"])
            for path in (registry.root / "workers").glob("*.json"):
                archive.write(path, "workers/" + path.name)
            if (registry.root / "report.md").exists():
                archive.write(registry.root / "report.md", "report.md")
            if (registry.root / "input.csv").exists():
                archive.write(registry.root / "input.csv", "input.csv")
        return stream.getvalue()
