"""
auth.py — Authentication Routes
---------------------------------
Exposes the GitHub OAuth 2.0 login flow as two FastAPI endpoints.

GET /auth/login
    Redirects the browser to GitHub's OAuth authorization page.

GET /auth/callback
    GitHub redirects here after user approval.
    Validates CSRF state, exchanges code for token, stores user in MongoDB,
    and returns a JSON SessionResponse with session_token + username.
"""

import secrets
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import RedirectResponse

from app.services import auth_service
from app.models.user import SessionResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── In-memory CSRF state store ─────────────────────────────────────────────────
# Holds state tokens issued by /login that haven't been consumed yet.
# A lightweight set is sufficient for a single-instance deployment.
# For multi-instance / production use: replace with a short-TTL Redis store.
_pending_states: set[str] = set()


# ── GET /auth/login ────────────────────────────────────────────────────────────

@router.get(
    "/login",
    summary="Initiate GitHub OAuth Login",
    description=(
        "Generates a secure CSRF state token and redirects the user's browser "
        "to GitHub's OAuth authorization page. The user will be asked to approve "
        "the requested scopes (`read:user`, `repo`). After approval, GitHub "
        "redirects to `/auth/callback`."
    ),
)
async def github_login():
    """
    Step 1 of OAuth 2.0:
      1. Generate a cryptographically random `state` token.
      2. Store it temporarily for CSRF validation in /callback.
      3. Build the GitHub authorization URL.
      4. Redirect the browser to GitHub.
    """
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)

    redirect_url = auth_service.build_github_redirect_url(state)
    return RedirectResponse(url=redirect_url)


# ── GET /auth/callback ─────────────────────────────────────────────────────────

@router.get(
    "/callback",
    response_model=SessionResponse,
    summary="GitHub OAuth Callback",
    description=(
        "Handles the redirect from GitHub after user authorization. "
        "Validates the CSRF state, exchanges the code for an access token, "
        "persists the user in MongoDB, and returns a `session_token` that must "
        "be sent as the `X-Session-Token` header on all `/github/*` calls."
    ),
)
async def github_callback(
    code: str = Query(..., description="One-time authorization code from GitHub."),
    state: str = Query(..., description="CSRF state token echoed back by GitHub."),
):
    """
    Step 2 of OAuth 2.0:
      1. Validate state (CSRF protection) — raise 400 if unknown.
      2. Exchange code → access_token via auth_service.
      3. Fetch the authenticated user's GitHub profile.
      4. Upsert the user document in MongoDB & generate a session_token.
      5. Return SessionResponse: { session_token, username, message }.
    """
    # ── CSRF validation ────────────────────────────────────────────────────────
    if state not in _pending_states:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state parameter. Possible CSRF attempt.",
        )
    _pending_states.discard(state)  # consume — each state is single-use

    # ── Exchange code for access token ─────────────────────────────────────────
    access_token = await auth_service.exchange_code_for_token(code)

    # ── Fetch GitHub user profile ──────────────────────────────────────────────
    github_user = await auth_service.fetch_github_user(access_token)

    # ── Persist user + token in MongoDB, get back a fresh session_token ────────
    session_token = await auth_service.upsert_user(github_user, access_token)

    return SessionResponse(
        message="Authentication successful",
        session_token=session_token,
        username=github_user["login"],
    )
