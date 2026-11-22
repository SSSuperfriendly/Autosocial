from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from autosocial.bootstrap import ensure_workspace
from server.auth import AuthSettings, OwnerAuthMiddleware
from server.routes.discovery import router as discovery_router
from server.routes.drafts import router as drafts_router
from server.routes.outreach import router as outreach_router
from server.routes.overview import router as overview_router
from server.routes.preferences import router as preferences_router
from server.routes.professors import router as professors_router
from server.routes.system import router as system_router
from server.routes.tracking import router as tracking_router
from server.routes.writer import router as writer_router


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"


def create_app() -> FastAPI:
    auth = AuthSettings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        auth.validate()
        ensure_workspace()
        yield

    application = FastAPI(title="AutoSocial API", version="0.4.0", lifespan=lifespan)
    application.add_middleware(OwnerAuthMiddleware, settings=auth)
    # CORS handles explicit-origin preflights before authentication; subsequent
    # requests still require the owner's credentials.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(auth.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

    for router in (
        system_router, writer_router, overview_router, preferences_router,
        discovery_router, professors_router, drafts_router, outreach_router, tracking_router,
    ):
        application.include_router(router)

    if FRONTEND_ASSETS.exists():
        application.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="assets")

    @application.get("/health")
    def healthcheck():
        return {"ok": True}

    def index_file() -> Path | None:
        candidate = FRONTEND_DIST / "index.html"
        return candidate if candidate.exists() else None

    @application.get("/")
    def serve_root():
        index = index_file()
        if index is None:
            return {
                "ok": True,
                "message": "前端尚未构建。请在 frontend 目录执行 npm ci 与 npm run build。",
            }
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @application.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith(("api/", "assets/")):
            raise HTTPException(status_code=404, detail="Not Found")
        # Files in Vite's public directory (favicon, icons) must be served as
        # assets rather than returning the SPA HTML under an image MIME type.
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        index = index_file()
        if index is None:
            raise HTTPException(status_code=503, detail="前端尚未构建，请在 frontend 目录执行 npm run build。")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
