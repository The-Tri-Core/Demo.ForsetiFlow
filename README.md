# Project Manager (Flask + HTML)

A minimal project/task tracker built with Flask and vanilla HTML/JS. Data is stored locally in SQLite and served from a lightweight API - no front-end build step required.

## Features
- Projects with descriptions and cascading deletes
- Tasks, Backlogs, Sprints, and Resources with basic fields (status, due dates, notes, velocity, etc.)
- Simple HTML UI powered by fetch calls to the REST API
- SQLite database persisted in `instance/project_manager.sqlite` (configurable via `PROJECT_DB`)

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
7) Open http://127.0.0.1:5000 in your browser.

## Running with Docker

**Docker Compose**: `docker compose up -d` then open <http://127.0.0.1:5000>

**Docker CLI**: `docker build -t project-manager . && docker run -d -p 5000:5000 -v ./data:/app/instance --name project-manager project-manager`

Data persists in `./data` directory. See environment variables below for configuration options.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Port the Flask server listens on |
| `PROJECT_DATA_DIR` | `/app/instance` | Directory where SQLite database is stored |
| `PROJECT_DB` | `project_manager.sqlite` | SQLite database filename |

## Configuration & Data

- Database file: `instance/project_manager.sqlite` (auto-created). Override with `PROJECT_DB=/path/to/db.sqlite`.
- To reset data, stop the app and delete the SQLite file (or point `PROJECT_DB` to a new path).

## API Overview
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
