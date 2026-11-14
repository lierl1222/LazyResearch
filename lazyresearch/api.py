import asyncio
import json
import os
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .configuration import load_model_config
from .models import ResearchTask
from .runner import Runner
from .results import result_markdown
from .session import Question, ask
from .research_service import ResearchService, Submission


def create_app(root: Path | None = None, *, runner: Runner | None = None, research_service=None) -> FastAPI:
    research_service = research_service or ResearchService(
        (root or Path(os.environ.get("LAZYRESEARCH_DIR", ".lazyresearch"))) / "research",
        load_model_config())
    runner = runner or load_model_config().runner(
        root or Path(os.environ.get("LAZYRESEARCH_DIR", ".lazyresearch")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ThreadPoolExecutor(max_workers=1) as pool:
            app.state.pool = pool
            for run_id in research_service.recover():
                pool.submit(research_service.run, run_id)
            for run_id in runner.storage.pending():
                pool.submit(runner.run, run_id)
            yield

    app = FastAPI(title="LazyResearch", lifespan=lifespan)

    @app.get("/research/config")
    def research_config():
        endpoints = research_service.config
        models = {}
        for name, endpoint in (("local", endpoints.local), ("cloud", endpoints.cloud)):
            ready = bool(endpoint.enabled and endpoint.base_url and endpoint.model)
            models[name] = {"ready": ready, "model": endpoint.model if ready else None}
        return {"mode": "research", "max_file_bytes": research_service.MAX_FILE_BYTES, "adapters": ["sequence", "cpu", "tabular"],
                "models": models}

    @app.post("/research/files", status_code=201)
    async def upload_research_file(name: str, request: Request):
        return await research_service.upload_stream(name, request.stream())

    @app.post("/research/runs/{id}/messages")
    def research_question(id: str, question: Question):
        return ask(research_service, id, question)

    @app.post("/research/runs", status_code=202)
    def start_research(task: Submission):
        if not any(e.enabled and e.base_url and e.model for e in
                   (research_service.config.local, research_service.config.cloud)):
            raise HTTPException(409, "请先配置至少一个模型端点")
        id = research_service.create(task)
        app.state.pool.submit(research_service.run, id)
        return {"id": id}

    @app.get("/research/runs/{id}")
    def research_snapshot(id: str):
        return research_service.snapshot(id)

    @app.post("/research/runs/{id}/stop")
    def stop_research(id: str):
        registry = research_service.registry(id)
        (registry.root / "stop.requested").touch()
        return {"status": "stop_requested"}

    @app.get("/research/runs/{id}/artifacts")
    def research_artifacts(id: str):
        return Response(research_service.bundle(id), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="research-{id}.zip"'})

    @app.get("/research/runs/{id}/result.md")
    def download_result(id: str):
        registry = research_service.registry(id)
        result = result_markdown(registry, registry.get("report"))
        if not result:
            raise HTTPException(409, "研究尚未结束")
        return Response(result, media_type="text/markdown", headers={
            "Content-Disposition": 'attachment; filename="result.md"'})

    @app.get("/research/runs/{id}/report")
    def live_research_report(id: str):
        registry = research_service.registry(id)
        path = registry.root / "report.md"
        return Response(path.read_text(encoding="utf-8") if path.exists() else "",
                        media_type="text/plain", headers={"Cache-Control": "no-store"})

    @app.get("/config")
    def config():
        return {"adapters": list(runner.adapters), "mode": runner.mode, "models": runner.model_status}

    @app.post("/runs", status_code=202)
    def start(task: ResearchTask):
        try:
            run_id = runner.create(task)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        app.state.pool.submit(runner.run, run_id)
        return {"id": run_id}

    @app.get("/runs/{run_id}")
    def snapshot(run_id: str):
        try:
            return runner.snapshot(run_id)
        except KeyError as error:
            raise HTTPException(404, "任务不存在") from error

    @app.get("/runs/{run_id}/events")
    def events(run_id: str, request: Request, last_event_id: int = Header(default=0)):
        snapshot(run_id)

        async def stream():
            after = last_event_id
            idle = 0
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(runner.storage.events, run_id, after)
                for event in batch:
                    after = event["id"]
                    yield f'id: {after}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                    if event.get("status") in {"finished", "failed"}:
                        return
                if not batch and await asyncio.to_thread(runner.storage.get, run_id, "final"):
                    # Final record and terminal event are committed together.
                    if not await asyncio.to_thread(runner.storage.events, run_id, after):
                        return
                    continue
                idle = 0 if batch else idle + 1
                if idle % 40 == 1:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/runs/{run_id}/artifacts")
    def artifacts(run_id: str):
        snapshot(run_id)
        try:
            bundle = runner.artifacts(run_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return Response(bundle, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="research-{run_id}.zip"'})

    frontend = Path(__file__).resolve().parents[1] / "web" / "dist"
    if frontend.is_dir():
        # Windows registry overrides may otherwise serve modules as text/plain.
        mimetypes.add_type("text/javascript", ".js")
        mimetypes.add_type("text/css", ".css")
        app.mount("/", StaticFiles(directory=frontend, html=True), name="workbench")
    return app
