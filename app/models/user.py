"""
user.py — Pydantic Models for User & Session
---------------------------------------------
Three models covering different layers of data exposure:

  UserInDB        → full document stored in MongoDB (includes token)
  SessionResponse → returned to client after successful OAuth login
  UserPublic      → safe subset (never exposes access_token)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Returns current UTC time (timezone-aware). Used as a field default."""
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    """Generates a fresh UUID4 string. Used as default for session_token."""
    return str(uuid.uuid4())


# ── DB Document Model ──────────────────────────────────────────────────────────

class UserInDB(BaseModel):
    """
    Full user document stored in MongoDB.
    Includes the OAuth access_token — never expose this over the API.
    """

    github_user_id: int = Field(
        ...,
        description="GitHub's numeric user ID (immutable, used as unique key in DB).",
    )
    username: str = Field(
        ...,
        description="GitHub login handle (e.g. 'octocat').",
    )
    access_token: str = Field(
        ...,
        description="GitHub OAuth access token. Used for all GitHub API calls.",
    )
    session_token: str = Field(
        default_factory=_new_uuid,
        description="UUID v4 issued to the client. Passed as X-Session-Token header.",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        description="Timestamp when the user first authenticated.",
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        description="Timestamp of the most recent re-authentication.",
    )


# ── API Response Models ────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    """
    Returned to the client after a successful /auth/callback.
    The client stores `session_token` and sends it as a header:
        X-Session-Token: <value>
    for all subsequent /github/* requests.
    """

    message: str = "Authentication successful"
    session_token: str = Field(..., description="UUID to use in X-Session-Token header.")
    username: str = Field(..., description="Authenticated GitHub username.")


class UserPublic(BaseModel):
    """
    Public-safe profile. Omits access_token and session_token.
    Safe to log or return in debugging endpoints.
    """

    github_user_id: int
    username: str
    created_at: datetime
    updated_at: datetime
