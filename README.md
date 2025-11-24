# Project Manager (Flask + HTML)

A minimal project/task tracker built with Flask and vanilla HTML/JS. Data is stored locally in SQLite and served from a lightweight API - no front-end build step required.

## Features
- Projects with descriptions and cascading deletes
- Tasks, Backlogs, Sprints, and Resources with basic fields (status, due dates, notes, velocity, etc.)
- Simple HTML UI powered by fetch calls to the REST API
- SQLite database persisted in `instance/project_manager.sqlite` (configurable via `PROJECT_DB`)
- Authy-backed login page that gates the `/app` workspace behind a two-step verification flow and forces credential rotation on first login

## Installation & Running
1) **Prerequisites**: Python 3.11+ and `pip` available in your PATH.
2) **Get the code**: clone or download this repository.
3) **Create a virtual environment**:
   - Windows (PowerShell/CMD): `python -m venv .venv`
   - macOS/Linux (bash): `python -m venv .venv`
4) **Activate the environment**:
   - Windows: `.\.venv\Scripts\activate`
   - macOS/Linux: `source .venv/bin/activate`
5) **Install dependencies**: `pip install -r requirements.txt`
6) **Start the app**:
   - Cross-platform: `python app.py`
   - Windows shortcut: double-click `start_project_manager.bat` (creates/activates `.venv`, installs deps, and starts the server).
7) Open http://127.0.0.1:51001 in your browser.

## Running with Docker

**Docker Compose**: `docker compose up -d` then open <http://127.0.0.1:51001>

**Docker CLI**: `docker build -t project-manager . && docker run -d -p 51001:51001 -v ./data:/app/instance --name project-manager project-manager`

Data persists in `./data` directory. See environment variables below for configuration options.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `51001` | Port the Flask server listens on |
| `PROJECT_DATA_DIR` | `/app/instance` | Directory where SQLite database is stored |
| `PROJECT_DB` | `project_manager.sqlite` | SQLite database filename |
| `AUTHY_API_KEY` | *(not set)* | Twilio Authy API key used to send verification codes |
| `AUTHY_API_URL` | `https://api.authy.com/protected/json` | Override if you are routing through a proxy |
| `AUTHY_VERIFICATION_VIA` | `sms` | Channel used to deliver codes (`sms`, `call`, etc.) |
| `FLASK_SECRET_KEY` | `dev-secret-key` | Secret key for Flask sessions and cookies |
| `LOGIN_TOKEN_TTL` | `300` | Seconds before a login verification token expires |
| `DEFAULT_ADMIN_USERNAME` | `admin` | Username for the seeded administrator account |
| `DEFAULT_ADMIN_PASSWORD` | `forseti` | Initial password for the seeded administrator account |
| `DEFAULT_ADMIN_EMAIL` | *(derived)* | Email stored for the seeded admin (defaults to `admin@example.com` when unset) |
| `DEFAULT_ADMIN_PHONE` | *(not set)* | Phone number Authy will call/SMS for the seeded admin (required to seed the account) |
| `DEFAULT_ADMIN_COUNTRY` | `1` | Country code used with the seeded admin phone number |

## User setup

Set `DEFAULT_ADMIN_PHONE` and `DEFAULT_ADMIN_COUNTRY` (plus optional `DEFAULT_ADMIN_EMAIL`) so the app can seed the administrator account with `DEFAULT_ADMIN_USERNAME`/`DEFAULT_ADMIN_PASSWORD` (defaults to `admin`/`forseti`). A seeded admin will receive Authy codes at that phone number and is forced to rotate the username or password on first login via `/account`. After at least one user exists, you must already be signed in (session cookie) before creating more users via `POST /api/users` using JSON such as `{ "username": "jdoe", "password": "secret", "phone_number": "1234567890", "country_code": "1", "email": "optional@example.com", "force_password_change": true }`.

## Authentication flow

1. Submit credentials via `POST /api/auth/start` (handled automatically by the login UI) to receive a login token and prompt Authy to send a code to the stored phone number. This endpoint expects `identifier` (username or email) and `password`.
2. Use the supplied token and the one-time code with `POST /api/auth/verify`. If the account still requires a credential rotation (e.g., the seeded admin), the server redirects to `/account`; otherwise it redirects to `/app` once the session is established.

## Configuration & Data

- Database file: `instance/project_manager.sqlite` (auto-created). Override with `PROJECT_DB=/path/to/db.sqlite`.
- To reset data, stop the app and delete the SQLite file (or point `PROJECT_DB` to a new path).

## API Overview
- `POST /api/users` - register a new user (requires admin/session once a user exists)
- `POST /api/auth/start` - begin Authy verification for a login attempt
- `POST /api/auth/verify` - verify the one-time code and mint a session
- `GET /api/projects` - list projects
- `POST /api/projects` - create project `{ name, description? }`
- `GET /api/projects/<project_id>/tasks` - list tasks
- `POST /api/projects/<project_id>/tasks` - create task `{ title, due_date?, status }`
- `PATCH /api/tasks/<task_id>` - update task fields
- `DELETE /api/tasks/<task_id>` - delete task
- `GET /api/backlogs/<project_id>` / `POST /api/backlogs/<project_id>` - list/create backlogs
- `PATCH /api/backlog/<backlog_id>` / `DELETE /api/backlog/<backlog_id>` - update/delete backlog
- `GET /api/sprints/<project_id>` / `POST /api/sprints/<project_id>` - list/create sprints
- `PATCH /api/sprint/<sprint_id>` / `DELETE /api/sprint/<sprint_id>` - update/delete sprint
- `GET /api/resources/<project_id>` / `POST /api/resources/<project_id>` - list/create resources
- `PATCH /api/resource/<resource_id>` / `DELETE /api/resource/<resource_id>` - update/delete resource

## Notes
- Debug mode is enabled by default in `app.py`; change `app.run(debug=True)` if needed.
- The HTML/JS frontend lives in `templates/` and `static/`; Flask serves them directly - no build step required.
