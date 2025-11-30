# Forseti Flow (Single-user, TOTP-only)

Forseti Flow is now an individual-use project/task tracker built with Flask and vanilla HTML/JS. Authentication is TOTP-only (Google/Microsoft Authenticator) and the app supports exactly one user at a time. The prior MSP tool idea and shared resource/assignee management have been removed.

## Features
- Single user with TOTP-only login (no username/password)
- First-time setup page with QR provisioning for authenticator apps
- Projects, Tasks, Backlogs, and Sprints
- Simple HTML UI powered by fetch calls to the REST API
- SQLite database persisted in `instance/project_manager.sqlite` (configurable via `PROJECT_DB`)

## Public Demo Mode

To simplify public trials, Forseti Flow can run in a "demo" mode that bypasses real authenticator setup and instead uses a single fixed TOTP code. In this mode the database is automatically reset every 24 hours to keep the environment clean.

Enable demo mode by setting environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEMO_MODE` | `1` (truthy) | Turn on public demo logic |
| `DEMO_TOTP_CODE` | `246810` | The single code accepted for login |

Behavior in demo mode:
- The setup flow (`/setup`) is skipped.
- Login accepts only the fixed `DEMO_TOTP_CODE`.
- A demo user is auto-created if none exists.
- MFA/account update screens do not require authenticator provisioning.
- Database file is deleted and reinitialized if older than 24h; a background thread schedules midnight UTC resets.

Disable demo mode by setting `DEMO_MODE=0` or `false`.

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

On first launch with zero users, you will be redirected to `/setup`, scan the QR with Google/Microsoft Authenticator, then enter the 6‑digit code to create the single user.

## Running with Docker

**Docker Compose**: `docker compose up -d` then open <http://127.0.0.1:51001>

**Docker CLI**: `docker run -d -p 51001:51001 -v ./data:/app/instance --name forsetiflow ghcr.io/Njordics/forsetiflow:latest`

Data persists in `./data` directory. See environment variables below for configuration options.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `51005` | Port the Flask server listens on |
| `PROJECT_DATA_DIR` | `/app/instance` | Directory where SQLite database is stored |
| `PROJECT_DB` | `project_manager.sqlite` | SQLite database filename |
| `FLASK_SECRET_KEY` | `dev-secret-key` | Secret key for Flask sessions and cookies |
| `MFA_ISSUER` | `Forseti Flow` | Issuer name displayed to authenticator apps when scanning the QR code |
| `DEMO_MODE` | `0` (off) | Enable public demo (fixed TOTP, daily reset) |
| `DEMO_TOTP_CODE` | `246810` | Fixed code for demo mode |

## Reset tool

- Click the Forseti logo on the login page to open the reset modal.
- Verify the reset pin to access the reset page and purge the user to re‑enable first-time setup.

## TOTP setup

When there are no users, the app shows a QR on the `/setup` page. Scan the QR with your authenticator app and submit the 6‑digit code to create the single user and sign in.

## Authentication flow

- TOTP-only:
   - First-time: `POST /api/auth/setup-first` with `{ "totp_code": "123456" }` to create the single user.
   - Login: `POST /api/auth/totp-login` with `{ "totp_code": "123456" }` to open the session.

## API Overview

- `POST /api/auth/setup-first` – first-time creation of the single user by verifying a TOTP from the scanned QR.
- `POST /api/auth/totp-login` – login with a 6‑digit code.
- `GET /api/projects`, `POST /api/projects`, and `GET /api/projects/<project_id>` – manage projects.
- `GET /api/projects/<project_id>/tasks`, `POST /api/projects/<project_id>/tasks`, `PATCH /api/tasks/<task_id>`, `DELETE /api/tasks/<task_id>` – manipulate tasks.
- `GET /api/backlogs/<project_id>` / `POST /api/backlogs/<project_id>` and `PATCH`/`DELETE /api/backlog/<item_id>` – handle backlogs.
- `GET /api/sprints/<project_id>` / `POST /api/sprints/<project_id>` and `PATCH`/`DELETE /api/sprint/<sprint_id>` – handle sprints.

## Configuration & Data

- Database file: `instance/project_manager.sqlite` (auto-created). Override with `PROJECT_DB=/path/to/db.sqlite`.
- To reset data, click the Forseti logo on the login page and follow the reset flow, or purge via `python scripts\delete_all_users.py --confirm`.

## Notes
- Debug mode is enabled by default in `app.py`; change `app.run(debug=True)` if needed.
- The HTML/JS frontend lives in `templates/` and `static/`; Flask serves them directly - no build step required.
- MSP tool idea and assignee/resource management have been removed for individual use design.
