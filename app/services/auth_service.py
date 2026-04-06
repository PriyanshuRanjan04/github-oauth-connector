"""
auth_service.py — GitHub OAuth 2.0 Business Logic
---------------------------------------------------
Owns the full OAuth handshake and token persistence layer.

Functions:
  build_github_redirect_url(state)      → str
  exchange_code_for_token(code)         → str
  fetch_github_user(access_token)       → dict
  upsert_user(user_data, access_token)  → str   (returns session_token)
  get_token_by_session(session_token)   → str   (returns access_token)
"""

import uuid
from urllib.parse import urlencode
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.db.mongodb import get_users_collection

# ── GitHub endpoint constants ──────────────────────────────────────────────────
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"


# ── 1. Build redirect URL ──────────────────────────────────────────────────────

def build_github_redirect_url(state: str) -> str:
    """
    Constructs the GitHub OAuth authorization URL.

    Scopes:
      - read:user  → read authenticated user's profile
      - repo       → full access to repos and issues

    The `state` param is a random token embedded in the URL and later
    echoed back by GitHub; we validate it in /callback to prevent CSRF.
    """
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.CALLBACK_URL,
        "scope": "read:user repo",
        "state": state,
    }
    return f"{_GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


# ── 2. Exchange code → access_token ───────────────────────────────────────────

async def exchange_code_for_token(code: str) -> str:
    """
    Sends the one-time OAuth code to GitHub and returns an access_token.

    GitHub requires:
        POST https://github.com/login/oauth/access_token
        Body: client_id, client_secret, code, redirect_uri
        Header: Accept: application/json

    Raises:
        HTTP 502  — GitHub returned an error or unexpected response
    """
    payload = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.CALLBACK_URL,
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(_GITHUB_TOKEN_URL, data=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub token endpoint returned {response.status_code}.",
        )

    data = response.json()

    # GitHub returns {"error": "...", "error_description": "..."} on failure
    if "error" in data:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub OAuth error: {data.get('error_description', data['error'])}",
        )

    access_token: str | None = data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="GitHub did not return an access_token.",
        )

    return access_token


# ── 3. Fetch GitHub user profile ──────────────────────────────────────────────

async def fetch_github_user(access_token: str) -> dict:
    """
    Calls GET /user on the GitHub API to retrieve the authenticated user's profile.

    Returns a dict containing at least:
        id       → github_user_id (int)
        login    → username (str)

    Raises:
        HTTP 401  — token is invalid or revoked
        HTTP 502  — GitHub API unreachable / unexpected error
    """
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(_GITHUB_USER_URL, headers=headers)

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid GitHub access token.")
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub /user endpoint returned {response.status_code}.",
        )

    return response.json()


# ── 4. Upsert user in MongoDB, return session_token ───────────────────────────

async def upsert_user(user_data: dict, access_token: str) -> str:
    """
    Inserts or updates the user document in MongoDB.

    - Uses `github_user_id` as the unique key (upsert).
    - Generates a fresh UUID session_token on every login.
    - Updates `access_token` and `updated_at` on re-authentication.
    - Sets `created_at` only on first insert ($setOnInsert).

    Returns:
        session_token (str) — UUID to be returned to the client
    """
    collection = get_users_collection()
    now = datetime.now(timezone.utc)
    session_token = str(uuid.uuid4())

    await collection.update_one(
        filter={"github_user_id": user_data["id"]},
        update={
            "$set": {
                "username": user_data["login"],
                "access_token": access_token,
                "session_token": session_token,
                "updated_at": now,
            },
            "$setOnInsert": {
                "github_user_id": user_data["id"],
                "created_at": now,
            },
        },
        upsert=True,
    )

    return session_token


# ── 5. Resolve session_token → access_token ───────────────────────────────────

async def get_token_by_session(session_token: str) -> str:
    """
    Looks up the stored access_token in MongoDB for a given session_token.

    Raises:
        HTTP 401  — session not found (invalid or expired token)

    Returns:
        access_token (str)
    """
    collection = get_users_collection()
    user = await collection.find_one(
        {"session_token": session_token},
        projection={"access_token": 1, "_id": 0},
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token. Please re-authenticate via /auth/login.",
        )

    return user["access_token"]
