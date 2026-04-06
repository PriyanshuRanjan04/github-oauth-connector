# 🔐 GitHub OAuth Connector

> A backend service that connects with GitHub using **OAuth 2.0**, allowing users to authenticate and perform real GitHub API actions through clean REST endpoints.

Built with **Python + FastAPI + MongoDB**, deployable on **Render**.

---

## 📋 Table of Contents

- [🛠️ Tech Stack](#️-tech-stack)
- [🧱 Project Structure](#-project-structure)
- [🔄 OAuth 2.0 Flow](#-oauth-20-flow)
- [🚀 Local Setup](#-local-setup)
- [📋 API Endpoints](#-api-endpoints)
- [🔐 Session Token Usage](#-session-token-usage)
- [⚠️ Error Handling](#️-error-handling)
- [☁️ Render Deployment](#️-render-deployment)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI |
| Language | Python 3.11+ |
| Auth | GitHub OAuth 2.0 |
| Database | MongoDB (Motor async driver) |
| HTTP Client | httpx (async) |
| Config | pydantic-settings |
| Server | Uvicorn |
| Hosting | Render |

---

## 🧱 Project Structure

```
github-oauth-connector/
│
├── app/
│   ├── main.py                 # App entry point, middleware, global handlers
│   ├── routes/
│   │   ├── auth.py             # /auth/login, /auth/callback
│   │   └── github.py           # /github/repos, /github/issues
│   ├── services/
│   │   ├── auth_service.py     # OAuth flow logic
│   │   └── github_service.py   # GitHub API calls
│   ├── db/
│   │   └── mongodb.py          # Async Motor connection
│   ├── models/
│   │   └── user.py             # Pydantic models
│   └── core/
│       └── config.py           # Environment variable loading
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🔄 OAuth 2.0 Flow

```
User                    Your API                  GitHub
 │                          │                        │
 │── GET /auth/login ──────►│                        │
 │                          │── Redirect ───────────►│
 │                          │   (client_id, state,   │
 │                          │    scope, redirect_uri)│
 │                          │                        │
 │◄── GitHub login page ──────────────────────────── │
 │── User approves ─────────────────────────────────►│
 │                          │                        │
 │                          │◄── GET /auth/callback ─│
 │                          │    (code, state)       │
 │                          │                        │
 │                          │─ POST token exchange ─►│
 │                          │◄── access_token ───────│
 │                          │                        │
 │                          │── GET /user ──────────►│
 │                          │◄── user profile ───────│
 │                          │                        │
 │                          │── Upsert MongoDB       │
 │                          │   Store access_token   │
 │                          │  Generate session_token│
 │                          │                        │
 │◄── { session_token,      │                        │
 │      username }          │                        │
```

💡 The returned `session_token` is a UUID that the client sends as the `X-Session-Token` header on all subsequent `/github/*` calls. It maps to the stored GitHub access token in MongoDB.

---

## 🚀 Local Setup

### ✅ Prerequisites

- 🐍 Python 3.11+
- 🗄️ MongoDB (local or [Atlas](https://cloud.mongodb.com))
- 🐙 A GitHub account

### 🔐 1. Create a GitHub OAuth App

1. Go to **GitHub → Settings → Developer Settings → OAuth Apps → New OAuth App**
2. Fill in:
   - **Application name**: `github-oauth-connector` (or anything)
   - **Homepage URL**: `http://localhost:8000`
   - **Authorization callback URL**: `http://localhost:8000/auth/callback`
3. Copy the **Client ID** and generate a **Client Secret**

### 📦 2. Clone & Install

```bash
git clone https://github.com/your-username/github-oauth-connector.git
cd github-oauth-connector

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

### 🌿 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
GITHUB_CLIENT_ID=your_actual_client_id
GITHUB_CLIENT_SECRET=your_actual_client_secret
CALLBACK_URL=http://localhost:8000/auth/callback
MONGO_URI=mongodb://localhost:27017
```

### 🚀 4. Run the Server

```bash
uvicorn app.main:app --reload
```

### 🧪 5. Open Swagger UI

```
http://localhost:8000/docs
```

---

## 📋 API Endpoints

### 🔐 Authentication

#### `GET /auth/login`
Redirects the browser to GitHub's OAuth authorization page.

**Usage:** Open this URL directly in a browser — it will redirect to GitHub.

```
GET http://localhost:8000/auth/login
```

---

#### `GET /auth/callback`
GitHub redirects here after user approval. Exchanges the code for a token, stores the user in MongoDB, and returns a `session_token`.

**Response:**
```json
{
  "message": "Authentication successful",
  "session_token": "3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "username": "octocat"
}
```

> ⚠️ **Save the `session_token`** — you'll use it as a header on all GitHub API calls.

---

### 🐙 GitHub API

> 🔐 All `/github/*` endpoints require the header:
> ```
> X-Session-Token: <your_session_token>
> ```

---

#### 📂 `GET /github/repos`
Fetches all repositories owned by the authenticated user.

**Request:**
```http
GET /github/repos
X-Session-Token: 3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c
```

**Response:**
```json
{
  "count": 2,
  "repos": [
    {
      "id": 123456789,
      "name": "my-repo",
      "full_name": "octocat/my-repo",
      "description": "A sample repository",
      "private": false,
      "language": "Python",
      "stars": 12,
      "forks": 3,
      "open_issues": 1,
      "url": "https://github.com/octocat/my-repo",
      "clone_url": "https://github.com/octocat/my-repo.git",
      "updated_at": "2026-04-05T10:00:00Z"
    }
  ]
}
```

---

#### 📂 `GET /github/issues?owner=&repo=`
Lists open issues for a specific repository.

**Request:**
```http
GET /github/issues?owner=octocat&repo=my-repo
X-Session-Token: 3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c
```

**Response:**
```json
{
  "owner": "octocat",
  "repo": "my-repo",
  "count": 1,
  "issues": [
    {
      "number": 42,
      "title": "Fix login bug",
      "body": "The login page throws an error on Safari.",
      "state": "open",
      "author": "octocat",
      "labels": ["bug"],
      "url": "https://github.com/octocat/my-repo/issues/42",
      "created_at": "2026-04-04T08:00:00Z",
      "updated_at": "2026-04-05T09:00:00Z"
    }
  ]
}
```

---

#### 📝 `POST /github/issues`
Creates a new issue in a specified repository.

**Request:**
```http
POST /github/issues
X-Session-Token: 3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c
Content-Type: application/json

{
  "owner": "octocat",
  "repo": "my-repo",
  "title": "Add dark mode support",
  "body": "Users have requested a dark mode option in the settings panel."
}
```

**Response `201 Created`:**
```json
{
  "message": "Issue created successfully.",
  "issue": {
    "number": 43,
    "title": "Add dark mode support",
    "body": "Users have requested a dark mode option in the settings panel.",
    "state": "open",
    "url": "https://github.com/octocat/my-repo/issues/43",
    "author": "octocat",
    "created_at": "2026-04-06T08:00:00Z"
  }
}
```

---

#### ✅ `GET /health`
Liveness check used by Render.

```json
{
  "status": "ok",
  "app": "GitHub OAuth Connector",
  "version": "1.0.0"
}
```

---

## 🔐 Session Token Usage

After a successful `/auth/callback`, you receive a `session_token` UUID. This token:

- 🗄️ Is stored in MongoDB linked to your GitHub access token
- 📤 Must be sent as the `X-Session-Token` header on every `/github/*` request
- 🔄 Is refreshed on every re-authentication (new UUID generated each time)

**🧪 In Swagger UI:**
1. Complete the OAuth flow via `/auth/login`
2. Copy the `session_token` from the `/auth/callback` response
3. Click **Authorize** in Swagger (lock icon) and paste: `your-session-token`
4. All subsequent requests will include the header automatically

---

## ⚠️ Error Handling

All errors return a consistent JSON envelope:

```json
{
  "error": true,
  "status_code": 404,
  "detail": "GitHub repository 'octocat/nonexistent' not found. Check owner/repo values.",
  "path": "/github/issues"
}
```

| Status | Cause |
|---|---|
| `400` | 🔐 Invalid CSRF state in OAuth callback |
| `401` | 🔐 Missing, invalid, or expired session token |
| `403` | ⛔ GitHub primary rate limit exceeded or insufficient OAuth scope |
| `404` | 🔍 Repository or endpoint not found |
| `422` | 📋 Request validation failed (missing/wrong fields) |
| `429` | ⏱️ GitHub secondary rate limit — includes `Retry-After` seconds |
| `500` | 💥 Unexpected internal server error |
| `502` | 🌐 GitHub API unreachable or unexpected response |

---

## ☁️ Render Deployment

### 🚀 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: GitHub OAuth Connector"
git remote add origin https://github.com/your-username/github-oauth-connector.git
git push -u origin main
```

### ☁️ 2. Create a Web Service on Render

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your GitHub repository
3. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port 10000`
   - **Environment:** Python 3

### 🌿 3. Add Environment Variables

In Render → **Environment** tab, add:

| Key | Value |
|---|---|
| `GITHUB_CLIENT_ID` | 🔐 Your GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | 🔐 Your GitHub OAuth App client secret |
| `MONGO_URI` | 🗄️ Your MongoDB Atlas connection string |
| `CALLBACK_URL` | ☁️ `https://your-app-name.onrender.com/auth/callback` |

### 🔐 4. Update GitHub OAuth App Callback URL

1. Go to **GitHub → Settings → Developer Settings → OAuth Apps**
2. Select your app
3. Update **Authorization callback URL** to:
   ```
   https://your-app-name.onrender.com/auth/callback
   ```

### 🧪 5. Deploy & Test

Once deployed, open:
```
https://your-app-name.onrender.com/docs
```

Follow the same flow: `/auth/login` → copy `session_token` → test GitHub endpoints.

---

## 📝 License

MIT
