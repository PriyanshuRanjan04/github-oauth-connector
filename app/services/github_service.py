"""
github_service.py — GitHub REST API Integration
-------------------------------------------------
All functions call the GitHub v3 API on behalf of the authenticated user.
They receive a valid `access_token` (resolved from session_token by the
route layer) and return cleaned, minimal response dicts.

Error mapping:
    401 → invalid / revoked token
    403 → rate-limited (primary) or insufficient scope
    404 → repository or resource not found
    422 → validation error (e.g. blank issue title)
    429 → secondary rate limit exceeded
    5xx → GitHub API failure
"""

import logging

import httpx
from fastapi import HTTPException

logger = logging.getLogger("github_connector.service")

_GITHUB_API = "https://api.github.com"


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _auth_headers(access_token: str) -> dict:
    """Standard headers attached to every GitHub API request."""
    return {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_github_status(response: httpx.Response, resource: str = "resource") -> None:
    """
    Translates GitHub HTTP error codes into meaningful FastAPI HTTPExceptions.
    Also logs a warning when the remaining rate-limit budget is low (<= 10).

    Args:
        response : The httpx response object.
        resource : Human-readable label for error messages (e.g. "repository").
    """
    code = response.status_code

    # ── Low rate-limit early warning (check on every response) ────────────────
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None and int(remaining) <= 10:
        reset_epoch = response.headers.get("X-RateLimit-Reset", "unknown")
        logger.warning(
            "⚠️  GitHub rate limit running low: %s requests remaining. Resets at epoch %s.",
            remaining, reset_epoch,
        )

    if code in (200, 201):
        return  # success — nothing to do

    # Try to extract GitHub's error message for context
    try:
        gh_message = response.json().get("message", "")
    except Exception:
        gh_message = response.text or "Unknown error"

    if code == 401:
        raise HTTPException(
            status_code=401,
            detail="GitHub rejected the access token. Please re-authenticate via /auth/login.",
        )
    if code == 403:
        # Primary rate-limit: GitHub returns 403 with a specific message
        reset_epoch = response.headers.get("X-RateLimit-Reset", "unknown")
        raise HTTPException(
            status_code=403,
            detail=(
                f"GitHub API forbidden. Possible rate-limit exceeded "
                f"(resets at epoch {reset_epoch}) or insufficient OAuth scope. "
                f"GitHub says: {gh_message}"
            ),
        )
    if code == 429:
        # Secondary rate-limit: GitHub returns 429 for burst / concurrent abuse
        retry_after = response.headers.get("Retry-After", "60")
        raise HTTPException(
            status_code=429,
            detail=(
                f"GitHub secondary rate limit exceeded. "
                f"Retry after {retry_after} seconds. "
                f"GitHub says: {gh_message}"
            ),
        )
    if code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"GitHub {resource} not found. Check owner/repo values.",
        )
    if code == 422:
        raise HTTPException(
            status_code=422,
            detail=f"GitHub validation error: {gh_message}",
        )
    # Catch-all for 5xx or anything unexpected
    raise HTTPException(
        status_code=502,
        detail=f"GitHub API returned an unexpected status {code}: {gh_message}",
    )


# ── 1. Fetch user repositories ─────────────────────────────────────────────────

async def get_user_repos(access_token: str) -> list[dict]:
    """
    GET /user/repos — returns all repos the authenticated user has access to.

    Sorted by last-updated, includes both public and private repos.
    Response is trimmed to the most useful fields.
    """
    params = {
        "sort": "updated",       # most recently active first
        "per_page": 100,         # max allowed by GitHub
        "affiliation": "owner",  # only repos the user owns
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_GITHUB_API}/user/repos",
            headers=_auth_headers(access_token),
            params=params,
        )

    _raise_for_github_status(response, "user repos")

    repos = response.json()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description"),
            "private": r["private"],
            "language": r.get("language"),
            "stars": r["stargazers_count"],
            "forks": r["forks_count"],
            "open_issues": r["open_issues_count"],
            "url": r["html_url"],
            "clone_url": r["clone_url"],
            "updated_at": r["updated_at"],
        }
        for r in repos
    ]


# ── 2. List repository issues ──────────────────────────────────────────────────

async def get_repo_issues(access_token: str, owner: str, repo: str) -> list[dict]:
    """
    GET /repos/{owner}/{repo}/issues — lists open issues for a repository.

    Returns issues only (not pull requests, which GitHub also stores as issues).
    Sorted by creation date descending.
    """
    params = {
        "state": "open",         # open issues only
        "sort": "created",
        "direction": "desc",
        "per_page": 50,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_GITHUB_API}/repos/{owner}/{repo}/issues",
            headers=_auth_headers(access_token),
            params=params,
        )

    _raise_for_github_status(response, f"repository '{owner}/{repo}'")

    issues = response.json()
    return [
        {
            "number": i["number"],
            "title": i["title"],
            "body": i.get("body"),
            "state": i["state"],
            "author": i["user"]["login"],
            "labels": [lbl["name"] for lbl in i.get("labels", [])],
            "url": i["html_url"],
            "created_at": i["created_at"],
            "updated_at": i["updated_at"],
        }
        for i in issues
        if "pull_request" not in i  # exclude PRs — they share the issues endpoint
    ]


# ── 3. Create a repository issue ───────────────────────────────────────────────

async def create_repo_issue(
    access_token: str,
    owner: str,
    repo: str,
    title: str,
    body: str = "",
) -> dict:
    """
    POST /repos/{owner}/{repo}/issues — creates a new issue.

    The authenticated user must have write access to the repository.
    `title` is required by GitHub; `body` is optional markdown text.
    """
    payload = {"title": title, "body": body}

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{_GITHUB_API}/repos/{owner}/{repo}/issues",
            headers=_auth_headers(access_token),
            json=payload,
        )

    _raise_for_github_status(response, f"repository '{owner}/{repo}'")

    issue = response.json()
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue.get("body"),
        "state": issue["state"],
        "url": issue["html_url"],
        "author": issue["user"]["login"],
        "created_at": issue["created_at"],
    }
