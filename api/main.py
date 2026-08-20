"""App factory: FastAPI instance, CORS, token middleware, health, routers."""

import threading
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

import db
import logs
from config import settings
from readers import get_reader
from readers.prompts import VERSION as PROMPT_VERSION
from readers.vision import calls_today
from routers import batches, jobs, records, specimens, store

# Mutating routes require ACCESS_TOKEN. Admin-only routes additionally require
# ADMIN_TOKEN. Matched by (method, path-prefix) since path params vary.
_ACCESS_ROUTES = [
    ("POST", "/api/records"),
    ("PATCH", "/api/records/"),
    ("POST", "/api/records/"),  # covers /api/records/{id}/verify
    ("POST", "/api/batches/"),  # stage, per-row assign, per-row upload
    ("DELETE", "/api/batches/"),
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


# PRD §8: per-IP rate limits on upload and verify. These are the two routes
# that cost money and disk - everything else is a read against SQLite.
_LIMITED_ROUTES = (("POST", "/api/records"), ("POST", "/api/jobs"))
_LIMIT_PER_MINUTE = 60
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def _over_limit(client_ip: str) -> bool:
    """Fixed 60-second window per IP.

    ponytail: in-process, so the effective ceiling is the limit times the
    worker count. That is the right order of magnitude for a two-worker
    single-tenant deployment; move it to SQLite or Redis if the service ever
    fronts more than one box.
    """
    now = time.time()
    with _hits_lock:
        recent = [t for t in _hits.get(client_ip, []) if now - t < 60]
        recent.append(now)
        _hits[client_ip] = recent
        return len(recent) > _LIMIT_PER_MINUTE


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        limited = any(
            request.method == m and request.url.path.startswith(p) for m, p in _LIMITED_ROUTES
        )
        if limited and _over_limit(request.client.host if request.client else "unknown"):
            logs.count("rate_limited")
            logs.event("rate_limited", path=request.url.path)
            return JSONResponse(
                {"detail": "too many requests; slow down and retry"}, status_code=429
            )
        return await call_next(request)


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


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with an id and log its outcome (PRD §8).

    Sits outside TokenMiddleware so a rejected request is logged too - a burst
    of 401s is exactly the thing you want a request id for.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("x-request-id") or logs.new_request_id()
        logs.set_request_id(request_id)
        started = time.perf_counter_ns()
        response = await call_next(request)
        # The path, not the URL: a query string carries reviewer search terms.
        logs.event(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter_ns() - started) / 1_000_000),
        )
        response.headers["x-request-id"] = request_id
        return response


class HealthResponse(BaseModel):
    store_readable: bool | None
    images_writable: bool | None
    reader_reachable: bool | None
    prompt_version: str | None
    provider: str
    model: str
    # Paid vision calls made since UTC midnight, against daily_vision_call_cap.
    calls_today: int = 0
    # PRD §8 service counters, since this process started.
    counters: dict[str, int] = {}


def create_app() -> FastAPI:
    logs.configure()
    db.init_db()

    app = FastAPI(title="TTB Label Verification API")

    app.add_middleware(TokenMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
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

        # Can the configured reader even be built? No network is involved -
        # VisionReader raises on a missing key at construction. This exists
        # because a process started against a stale READER_PROVIDER read every
        # label with the OCR fallback for an afternoon and nothing said so:
        # settings are parsed at import, so the running value is the only
        # value that matters and it has to be observable.
        try:
            get_reader()
            reader_reachable: bool | None = True
        except Exception:  # noqa: BLE001
            reader_reachable = False

        return HealthResponse(
            store_readable=store_readable,
            images_writable=images_writable,
            reader_reachable=reader_reachable,
            # Only a vision reading is produced by a prompt.
            prompt_version=PROMPT_VERSION if settings.reader_provider == "openai" else None,
            provider=settings.reader_provider,
            model=settings.reader_model,
            # PRD §5.1 asks for dollars; reporting those honestly needs a
            # per-model price table, so the enforced backstop counts calls.
            calls_today=calls_today(),
            counters=logs.counters(),
        )

    return app


app = create_app()
