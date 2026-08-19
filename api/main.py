"""App factory: FastAPI instance, CORS, token middleware, health, routers."""

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

import db
from config import settings
from routers import batches, jobs, records, specimens, store

# Mutating routes require ACCESS_TOKEN. Admin-only routes additionally require
# ADMIN_TOKEN. Matched by (method, path-prefix) since path params vary.
_ACCESS_ROUTES = [
    ("POST", "/api/records"),
    ("PATCH", "/api/records/"),
    ("POST", "/api/records/"),  # covers /api/records/{id}/verify
    ("POST", "/api/batches/stage"),
    ("POST", "/api/jobs"),
    ("POST", "/api/fixtures"),
]
_ADMIN_ROUTES = [
    ("POST", "/api/store/import"),
]
# POST /api/fixtures is access-gated always here; its additional ADMIN_TOKEN
# requirement for mode: "reset" (PRD §5.1, §8) depends on the request body,
# so that half of the check belongs in the route handler once it exists (M1),
# not in this path/method-based middleware.


class TokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method, path = request.method, request.url.path

        needs_admin = any(
            method == m and path.startswith(prefix) for m, prefix in _ADMIN_ROUTES
        )
        needs_access = needs_admin or any(
            method == m and path.startswith(prefix) for m, prefix in _ACCESS_ROUTES
        )

        if needs_access or needs_admin:
            auth = request.headers.get("authorization", "")
            token = auth.removeprefix("Bearer ").strip() if auth else ""
            if needs_admin:
                ok = bool(settings.admin_token) and token == settings.admin_token
            else:
                # The admin token satisfies any access-only route too - an
                # admin can do everything a reviewer can. Reject an empty
                # token outright so an unset admin_token can't match one.
                valid = {t for t in (settings.access_token, settings.admin_token) if t}
                ok = bool(token) and token in valid
            if not ok:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)

        return await call_next(request)


class HealthResponse(BaseModel):
    store_readable: bool | None
    images_writable: bool | None
    reader_reachable: bool | None
    prompt_version: str | None
    provider: str
    model: str
    spend_today_usd: float | None


def create_app() -> FastAPI:
    db.init_db()

    app = FastAPI(title="TTB Label Verification API")

    app.add_middleware(TokenMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # In production Caddy serves the data volume directly (PRD §9) and these
    # never reach the app. Locally there is no Caddy, so the API stands in.
    images = db.data_dir() / "images"
    images.mkdir(parents=True, exist_ok=True)
    app.mount("/api/images", StaticFiles(directory=images), name="images")

    app.include_router(records.router, prefix="/api")
    app.include_router(batches.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(store.router, prefix="/api")
    app.include_router(specimens.router, prefix="/api")

    @app.get("/api/health")
    def health() -> HealthResponse:
        # Reader reachability and prompt version are M3 concerns - no reader
        # exists yet, so those fields stay honest placeholders until then.
        # Deliberately blind: a health endpoint must report "unhealthy" for
        # any storage failure, not just the ones we anticipated.
        try:
            db.init_db()
            store_readable: bool | None = True
        except Exception:  # noqa: BLE001
            store_readable = False
        try:
            images_writable = db.data_dir().joinpath("images").is_dir()
        except Exception:  # noqa: BLE001
            images_writable = False
        return HealthResponse(
            store_readable=store_readable,
            images_writable=images_writable,
            reader_reachable=None,
            prompt_version=None,
            provider=settings.reader_provider,
            model=settings.reader_model,
            spend_today_usd=None,
        )

    return app


app = create_app()
