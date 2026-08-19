"""App factory: FastAPI instance, CORS, token middleware, health, routers."""

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from config import settings
from routers import batches, jobs, records, store

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
            required = settings.admin_token if needs_admin else settings.access_token
            if not required or token != required:
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
    app = FastAPI(title="TTB Label Verification API")

    app.add_middleware(TokenMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(records.router, prefix="/api")
    app.include_router(batches.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(store.router, prefix="/api")

    @app.get("/api/health")
    def health() -> HealthResponse:
        # M0: no store, no image volume, no reader exist yet (M1/M3). These
        # fields report the wiring status honestly rather than faking a check
        # against a system that does not exist.
        return HealthResponse(
            store_readable=None,
            images_writable=None,
            reader_reachable=None,
            prompt_version=None,
            provider=settings.reader_provider,
            model=settings.reader_model,
            spend_today_usd=None,
        )

    return app


app = create_app()
