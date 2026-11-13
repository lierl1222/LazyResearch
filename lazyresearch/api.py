import asyncio
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import ResearchTask
from .runner import Runner


def create_app(root: Path | None = None, *, runner: Runner | None = None) -> FastAPI:
    runner = runner or Runner(root or Path(os.environ.get("LAZYRESEARCH_DIR", ".lazyresearch")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ThreadPoolExecutor(max_workers=1) as pool:
            app.state.pool = pool
            for run_id in runner.storage.pending():
                pool.submit(runner.run, run_id)
            yield

    app = FastAPI(title="LazyResearch", lifespan=lifespan)

    @app.get("/config")
    def config():
        return {"adapters": list(runner.adapters), "mode": runner.mode}

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
        # Windows registry settings can otherwise cause browsers to reject JS modules.
        mimetypes.add_type("text/javascript", ".js")
        app.mount("/", StaticFiles(directory=frontend, html=True), name="workbench")
    return app
