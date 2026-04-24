"""Inspector Starlette app — REST proxy + SSE fan-out + static SPA."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .events import EventHub
from .proxy import InspectorProxy, InspectorProxyError

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(proxy: InspectorProxy) -> Starlette:
    """Construct the Starlette app, wiring the EventHub through app.state."""
    hub = EventHub(proxy)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await hub.start()
        logger.info("[inspector] EventHub started")
        try:
            yield
        finally:
            await hub.stop()
            logger.info("[inspector] EventHub stopped")

    async def index(request: Request) -> Response:
        path = STATIC_DIR / "index.html"
        if path.exists():
            return FileResponse(path)
        return JSONResponse({"error": "UI not built"}, status_code=404)

    async def healthz(request: Request) -> Response:
        return JSONResponse({"ok": True})

    async def overview(request: Request) -> Response:
        try:
            data = await hub.get_overview()
            return JSONResponse(data)
        except InspectorProxyError as e:
            return JSONResponse({"error": str(e)}, status_code=502)

    async def server_status(request: Request) -> Response:
        server_id = request.query_params.get("server_id")
        if not server_id:
            return JSONResponse({"error": "missing server_id"}, status_code=400)
        kind, _, rest = server_id.partition("::")
        try:
            if kind == "cp":
                data = await proxy.get_cp_mcp_status(rest)
            elif kind.startswith("runner:"):
                runner = kind.split(":", 1)[1]
                data = await proxy.get_runner_mcp_status(runner, rest)
            elif kind == "native":
                data = {"name": rest, "status": "connected", "tool_count": 0}
            else:
                return JSONResponse({"error": f"unknown server_id: {server_id}"}, status_code=400)
            return JSONResponse(data)
        except InspectorProxyError as e:
            return JSONResponse({"error": str(e)}, status_code=502)

    async def refresh(request: Request) -> Response:
        server_id = request.query_params.get("server_id")
        hub.broadcast({"event": "refresh_started", "data": {"server_id": server_id or "*"}})
        try:
            if not server_id:
                result = await proxy.refresh_tools()
            else:
                kind, _, rest = server_id.partition("::")
                if kind == "cp":
                    result = await proxy.refresh_tools(server=rest)
                elif kind.startswith("runner:"):
                    return JSONResponse(
                        {
                            "error": "Runner-hosted server refresh is deferred; "
                            "refreshes automatically on runner reconnect."
                        },
                        status_code=501,
                    )
                elif kind == "native":
                    return JSONResponse(
                        {"error": "Native tools cannot be refreshed."},
                        status_code=400,
                    )
                else:
                    return JSONResponse(
                        {"error": f"unknown server_id: {server_id}"}, status_code=400
                    )
            hub.broadcast(
                {
                    "event": "refresh_completed",
                    "data": {
                        "server_id": server_id or "*",
                        "tool_count": result.get("refreshed", 0),
                    },
                }
            )
            return JSONResponse(result)
        except InspectorProxyError as e:
            return JSONResponse({"error": str(e)}, status_code=502)

    async def events(request: Request) -> Response:
        queue = hub.subscribe()

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                    except asyncio.TimeoutError:
                        continue
                    yield {
                        "event": evt.get("event", "message"),
                        "data": json.dumps(evt.get("data", {})),
                    }
            finally:
                hub.unsubscribe(queue)

        return EventSourceResponse(event_generator())

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/api/overview", overview, methods=["GET"]),
        Route("/api/refresh", refresh, methods=["POST"]),
        Route("/api/server/status", server_status, methods=["GET"]),
        Route("/events", events, methods=["GET"]),
    ]
    if STATIC_DIR.exists():
        routes.append(Mount("/static", StaticFiles(directory=str(STATIC_DIR))))

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
    )
    app.state.hub = hub
    return app


async def run_inspector_server(
    proxy: InspectorProxy,
    host: str,
    port: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the inspector Starlette app under uvicorn until ``shutdown_event`` is set."""
    app = create_app(proxy)
    config = uvicorn.Config(app, host=host, port=port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)

    serve_task = asyncio.create_task(server.serve())
    try:
        await shutdown_event.wait()
    finally:
        server.should_exit = True
        await serve_task
