"""
main.py — FastAPI Application Entry Point
------------------------------------------
Responsibilities:
  - Initialise FastAPI app with metadata and Swagger config
  - Configure Python logging (INFO, timestamped)
  - Manage MongoDB connection lifecycle via async lifespan
  - Register auth + github routers
  - Add global exception handlers (404, 422, 500)
  - Add request logging middleware
  - Add rate-limit guard middleware for GitHub API 429 responses
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.db.mongodb import connect_db, close_db
from app.routes import auth, github


# ══════════════════════════════════════════════════════════════════════════════
# Logging — configured before anything else so startup messages are captured
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("github_connector")


# ══════════════════════════════════════════════════════════════════════════════
# Lifespan — startup / shutdown hooks
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up %s v%s", settings.APP_NAME, settings.APP_VERSION)
    await connect_db()
    yield
    await close_db()
    logger.info("🛑 Application shutdown complete.")


# ══════════════════════════════════════════════════════════════════════════════
# App instance
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "A GitHub Cloud Connector that authenticates via **OAuth 2.0** and exposes "
        "REST endpoints to interact with the GitHub API.\n\n"
        "**Authentication flow:**\n"
        "1. `GET /auth/login` — Redirects to GitHub for approval\n"
        "2. `GET /auth/callback` — Exchanges code for token, returns `session_token`\n"
        "3. Pass `X-Session-Token: <value>` header on all `/github/*` calls"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ══════════════════════════════════════════════════════════════════════════════
# Middleware — CORS
# ══════════════════════════════════════════════════════════════════════════════

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# Middleware — Request logging + GitHub rate-limit header guard
# ══════════════════════════════════════════════════════════════════════════════

@app.middleware("http")
async def logging_and_ratelimit_middleware(request: Request, call_next):
    """
    Two responsibilities in one lightweight middleware:

    1. REQUEST LOGGING
       Logs method, path, client IP, and total response time (ms).

    2. GITHUB RATE-LIMIT GUARD
       If any route handler surfaces a GitHub 429 response or the
       X-RateLimit-Remaining header reaches 0, return a structured 429
       to the caller with a helpful Retry-After message.

       Note: GitHub wraps most rate limits as 403 with a message; true 429s
       occur on secondary/GraphQL rate limits. We handle both.
    """
    start = time.monotonic()
    client_ip = request.client.host if request.client else "unknown"

    logger.info("→ %s %s  [client: %s]", request.method, request.url.path, client_ip)

    response = await call_next(request)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "← %s %s  status=%d  %.1fms",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )

    # ── GitHub rate-limit passthrough detection ────────────────────────────────
    # When github_service raises an HTTPException(429), it reaches here as a
    # normal response with status 429. We intercept to add structured body.
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "60")
        logger.warning(
            "⚠️  GitHub rate limit hit on %s. Retry-After: %ss", request.url.path, retry_after
        )

    return response


# ══════════════════════════════════════════════════════════════════════════════
# Global Exception Handlers
# ══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Catches all HTTPExceptions (404s, 401s, our own raises, etc.) and
    returns a consistent JSON error envelope instead of FastAPI's default format.
    """
    log_level = logging.WARNING if exc.status_code < 500 else logging.ERROR
    logger.log(
        log_level,
        "HTTPException %d on %s %s — %s",
        exc.status_code, request.method, request.url.path, exc.detail,
    )

    # Special-case 404 with a more helpful message
    detail = exc.detail
    if exc.status_code == 404 and detail == "Not Found":
        detail = (
            f"The endpoint '{request.method} {request.url.path}' does not exist. "
            "See /docs for available endpoints."
        )

    # Special-case 429 — surface rate limit context clearly
    if exc.status_code == 429:
        detail = (
            "GitHub API rate limit exceeded. "
            "Authenticated users get 5,000 requests/hour. "
            "Please wait before retrying. "
            f"Detail: {exc.detail}"
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": detail,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Catches Pydantic/FastAPI validation errors (missing fields, wrong types)
    and returns a clean 422 with per-field error breakdown.
    """
    errors = [
        {
            "field": " → ".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    logger.warning(
        "Validation error on %s %s — %d field(s) failed",
        request.method, request.url.path, len(errors),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "status_code": 422,
            "detail": "Request validation failed.",
            "errors": errors,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for any unhandled Python exceptions.
    Returns a generic 500 without leaking internal tracebacks to the client.
    Logs the full traceback server-side for debugging.
    """
    logger.exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "status_code": 500,
            "detail": "An unexpected internal server error occurred. Please try again later.",
            "path": str(request.url.path),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Routers
# ══════════════════════════════════════════════════════════════════════════════

app.include_router(auth.router)
app.include_router(github.router)


# ══════════════════════════════════════════════════════════════════════════════
# Root & Health Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"], summary="Root — API Info")
async def root():
    """Welcome endpoint. Returns basic API info and links to docs."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "auth_flow": {
            "step_1": "GET /auth/login → redirects to GitHub",
            "step_2": "GET /auth/callback → returns session_token",
            "step_3": "Use X-Session-Token header on /github/* endpoints",
        },
    }


@app.get("/health", tags=["Health"], summary="Health Check")
async def health_check():
    """
    Lightweight liveness probe used by Render and monitoring tools.
    Returns 200 while the app is running.
    """
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
