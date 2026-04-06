"""
github.py — GitHub API Routes
------------------------------
All three endpoints share a single FastAPI dependency (`resolve_access_token`)
that reads the X-Session-Token header, looks up the user's GitHub access_token
from MongoDB, and injects it directly into the route handler.

Endpoints:
    GET  /github/repos          → fetch authenticated user's repositories
    GET  /github/issues         → list open issues for owner/repo
    POST /github/issues         → create a new issue in owner/repo
"""

from fastapi import APIRouter, Depends, Header, Query, HTTPException
from pydantic import BaseModel, Field

from app.services import auth_service, github_service

router = APIRouter(prefix="/github", tags=["GitHub"])


# ── Shared Session Dependency ──────────────────────────────────────────────────

async def resolve_access_token(
    x_session_token: str = Header(
        ...,
        alias="X-Session-Token",
        description=(
            "Session token returned by `/auth/callback`. "
            "Used to look up your GitHub access token from the database."
        ),
    )
) -> str:
    """
    FastAPI dependency injected into every /github/* route.

    Reads the X-Session-Token header, queries MongoDB for the
    matching access_token, and returns it.

    Raises:
        HTTP 401 — if the session token is missing, invalid, or not found.
    """
    return await auth_service.get_token_by_session(x_session_token)


# ── Request / Response Models ──────────────────────────────────────────────────

class CreateIssueRequest(BaseModel):
    """Request body for POST /github/issues."""
    owner: str = Field(..., description="GitHub username or organisation that owns the repo.")
    repo: str = Field(..., description="Repository name (without owner prefix).")
    title: str = Field(..., min_length=1, description="Issue title — cannot be blank.")
    body: str = Field("", description="Issue description in markdown (optional).")


# ── GET /github/repos ──────────────────────────────────────────────────────────

@router.get(
    "/repos",
    summary="Fetch Authenticated User's Repositories",
    description=(
        "Returns all GitHub repositories owned by the authenticated user, "
        "sorted by most recently updated. Requires a valid `X-Session-Token` header."
    ),
)
async def fetch_repos(
    access_token: str = Depends(resolve_access_token),
):
    """
    Calls GitHub GET /user/repos on behalf of the session user.
    Returns a list of repos with name, description, stars, language, url, etc.
    """
    repos = await github_service.get_user_repos(access_token)
    return {
        "count": len(repos),
        "repos": repos,
    }


# ── GET /github/issues ─────────────────────────────────────────────────────────

@router.get(
    "/issues",
    summary="List Open Issues for a Repository",
    description=(
        "Returns all open issues (excluding pull requests) for the specified repository. "
        "Pass `owner` and `repo` as query parameters."
    ),
)
async def list_issues(
    owner: str = Query(..., description="GitHub username or org that owns the repo."),
    repo: str = Query(..., description="Repository name."),
    access_token: str = Depends(resolve_access_token),
):
    """
    Calls GitHub GET /repos/{owner}/{repo}/issues.
    Returns issue number, title, body, author, labels, and url.
    """
    if not owner.strip() or not repo.strip():
        raise HTTPException(status_code=400, detail="`owner` and `repo` query params cannot be empty.")

    issues = await github_service.get_repo_issues(access_token, owner.strip(), repo.strip())
    return {
        "owner": owner,
        "repo": repo,
        "count": len(issues),
        "issues": issues,
    }


# ── POST /github/issues ────────────────────────────────────────────────────────

@router.post(
    "/issues",
    status_code=201,
    summary="Create a New Issue",
    description=(
        "Creates a new GitHub issue in the specified repository. "
        "The authenticated user must have write access to the repo. "
        "`title` is required; `body` is optional markdown text."
    ),
)
async def create_issue(
    payload: CreateIssueRequest,
    access_token: str = Depends(resolve_access_token),
):
    """
    Calls GitHub POST /repos/{owner}/{repo}/issues.
    Returns the created issue's number, title, url, and author.
    """
    created = await github_service.create_repo_issue(
        access_token=access_token,
        owner=payload.owner.strip(),
        repo=payload.repo.strip(),
        title=payload.title.strip(),
        body=payload.body,
    )
    return {
        "message": "Issue created successfully.",
        "issue": created,
    }
