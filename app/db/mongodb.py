"""
mongodb.py — Async MongoDB Connection via Motor
------------------------------------------------
Manages a single AsyncIOMotorClient shared across the app lifetime.
Connection is opened on FastAPI startup and closed on shutdown
via the lifespan context manager in main.py.

Usage:
    from app.db.mongodb import get_users_collection
    collection = get_users_collection()
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from app.core.config import settings

logger = logging.getLogger("github_connector.db")

# ── Module-level state ─────────────────────────────────────────────────────────
_client: AsyncIOMotorClient | None = None
_db = None


# ── Lifecycle helpers (called from main.py lifespan) ──────────────────────────

async def connect_db() -> None:
    """
    Opens the MongoDB connection and pins the database.
    Called once at application startup.
    Ping is attempted as an early connectivity check; failure is logged as a
    warning (not a crash) so the server can still start for local dev.
    """
    global _client, _db
    _client = AsyncIOMotorClient(settings.MONGO_URI)
    _db = _client["github_connector"]

    try:
        await _client.admin.command("ping")
        logger.info("✅ MongoDB connected successfully.")
    except Exception as exc:
        logger.warning(
            "⚠️  MongoDB ping failed at startup: %s — "
            "DB-dependent routes will error until a connection is available.",
            exc,
        )


async def close_db() -> None:
    """
    Closes the MongoDB connection gracefully.
    Called once at application shutdown.
    """
    global _client
    if _client is not None:
        _client.close()
        print("🔌 MongoDB connection closed.")


# ── Collection accessors ───────────────────────────────────────────────────────

def get_users_collection() -> AsyncIOMotorCollection:
    """
    Returns the `users` collection.

    Schema (per document):
        github_user_id : int   — unique GitHub numeric user ID  (indexed)
        username       : str   — GitHub login handle
        access_token   : str   — GitHub OAuth access token
        session_token  : str   — UUID issued to the client after OAuth
        created_at     : datetime
        updated_at     : datetime
    """
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect_db() first.")
    return _db["users"]
