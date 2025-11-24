import os
import secrets
import shutil
import sqlite3
import tempfile
import time

import requests
from flask import Flask, render_template, request, jsonify, abort, g, session, redirect, url_for
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-secret-key"

# Location for the SQLite file. Defaults to a user-writable folder so clones don't hit permission errors.
_default_home = os.path.join(os.path.expanduser("~"), ".project_manager_data")
_default_tmp = os.path.join(tempfile.gettempdir(), "project_manager_data")
DATA_DIR = os.environ.get("PROJECT_DATA_DIR") or _default_home
if not os.access(os.path.dirname(DATA_DIR) or ".", os.W_OK):
    DATA_DIR = _default_tmp
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILENAME = os.environ.get("PROJECT_DB", "project_manager.sqlite")
DB_PATH = os.path.join(DATA_DIR, DB_FILENAME)
SEED_DB_PATH = os.path.join(app.instance_path, DB_FILENAME)

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

DEFAULT_ADMIN_USERNAME = os.environ.get("DEFAULT_ADMIN_USERNAME") or "admin"
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD") or "forseti"
DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL")
DEFAULT_ADMIN_PHONE = os.environ.get("DEFAULT_ADMIN_PHONE")
DEFAULT_ADMIN_COUNTRY = os.environ.get("DEFAULT_ADMIN_COUNTRY")

AUTHY_API_KEY = os.environ.get("AUTHY_API_KEY")
AUTHY_API_URL = os.environ.get("AUTHY_API_URL") or "https://api.authy.com/protected/json"
AUTHY_VERIFICATION_VIA = os.environ.get("AUTHY_VERIFICATION_VIA") or "sms"
AUTHY_CODE_LENGTH = _int_env("AUTHY_CODE_LENGTH", 6)
LOGIN_TOKEN_TTL = _int_env("LOGIN_TOKEN_TTL", 300)


def ensure_db_permissions():
    """Make DB and its directory world-writable so users don't hit permission issues."""
    try:
        os.chmod(DATA_DIR, 0o777)
    except OSError:
        pass
    if os.path.exists(DB_PATH):
        try:
            os.chmod(DB_PATH, 0o666)
        except OSError:
            pass


def ensure_db_exists():
    """If DB doesn't exist in DATA_DIR, seed it from packaged instance copy when available."""
    if not os.path.exists(DB_PATH) and os.path.exists(SEED_DB_PATH):
        try:
            shutil.copy2(SEED_DB_PATH, DB_PATH)
        except OSError:
            pass


def get_db():
    if "db" not in g:
        ensure_db_exists()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
        ensure_db_permissions()
    return g.db


def mask_phone_number(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) <= 4:
        return phone or ""
    return f"••••{digits[-4:]}"


def start_phone_verification(phone_number: str, country_code: str) -> dict:
    if not AUTHY_API_KEY:
        return {"success": False, "message": "Two-factor authentication is not configured."}
    payload = {
        "phone_number": phone_number,
        "country_code": country_code,
        "via": AUTHY_VERIFICATION_VIA,
        "code_length": AUTHY_CODE_LENGTH,
    }
    headers = {"X-Authy-API-Key": AUTHY_API_KEY}
    try:
        response = requests.post(
            f"{AUTHY_API_URL}/phones/verification/start",
            data=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        message = str(exc)
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                message = resp.json().get("message") or resp.text or message
            except ValueError:
                message = resp.text or message
        return {"success": False, "message": message}


def check_phone_verification(phone_number: str, country_code: str, code: str) -> dict:
    if not AUTHY_API_KEY:
        return {"success": False, "message": "Two-factor authentication is not configured."}
    params = {
        "phone_number": phone_number,
        "country_code": country_code,
        "verification_code": code,
    }
    headers = {"X-Authy-API-Key": AUTHY_API_KEY}
    try:
        response = requests.get(
            f"{AUTHY_API_URL}/phones/verification/check",
            params=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        message = str(exc)
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                message = resp.json().get("message") or resp.text or message
            except ValueError:
                message = resp.text or message
        return {"success": False, "message": message}


def ensure_default_admin_user(db):
    if not (DEFAULT_ADMIN_PHONE and DEFAULT_ADMIN_COUNTRY):
        return
    try:
        total = db.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
    except sqlite3.OperationalError:
        return
    if total:
        return
    password_hash = generate_password_hash(DEFAULT_ADMIN_PASSWORD)
    email = DEFAULT_ADMIN_EMAIL or f"{DEFAULT_ADMIN_USERNAME}@example.com"
    try:
        db.execute(
            "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials) VALUES (?, ?, ?, ?, ?, 1)",
            (email, DEFAULT_ADMIN_USERNAME, password_hash, DEFAULT_ADMIN_PHONE, DEFAULT_ADMIN_COUNTRY),
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass


def login_required(view):
    exempt_endpoints = {"account_page", "logout"}

    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login_page"))

        if session.get("needs_update"):
            endpoint = request.endpoint or ""
            if endpoint not in exempt_endpoints:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "update credentials required"}), 403
                return redirect(url_for("account_page"))

        return view(*args, **kwargs)

    return wrapped


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT ''
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'todo',
            due_date TEXT DEFAULT '',
            resource_id INTEGER DEFAULT NULL,
            parent_id INTEGER DEFAULT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS backlogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'todo',
            tags TEXT DEFAULT '',
            resource_id INTEGER DEFAULT NULL,
            parent_id INTEGER DEFAULT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS sprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            velocity INTEGER DEFAULT 0,
            scope_points INTEGER DEFAULT 0,
            done_points INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'free',
            notes TEXT DEFAULT '',
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            country_code TEXT NOT NULL,
            must_update_credentials INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN parent_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN description TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE backlogs ADD COLUMN parent_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN resource_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE backlogs ADD COLUMN resource_id INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN username TEXT UNIQUE")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("UPDATE users SET username = email WHERE username IS NULL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN must_update_credentials INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("UPDATE users SET must_update_credentials = 0 WHERE must_update_credentials IS NULL")
    except sqlite3.OperationalError:
        pass
    db.commit()

with app.app_context():
    init_db()


def require_project(project_id: str):
    db = get_db()
    row = db.execute(
        "SELECT id, name, description FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        abort(404, "Project not found.")
    return dict(row)


def get_user_by_identifier(identifier: str):
    db = get_db()
    return db.execute(
        """
        SELECT id, email, username, password_hash, phone_number, country_code, must_update_credentials
        FROM users
        WHERE username = ? OR email = ?
        """,
        (identifier, identifier),
    ).fetchone()


def get_user_by_id(user_id: int):
    db = get_db()
    return db.execute(
        """
        SELECT id, email, username, phone_number, country_code, must_update_credentials
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def render_login_view():
    init_db()
    return render_template("login.html")


@app.route("/")
@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index_page"))
    return render_login_view()


@app.route("/app")
@login_required
def index_page():
    init_db()
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login_page"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account_page():
    user = get_user_by_id(session["user_id"])
    if not user:
        abort(404, "User not found.")
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not username:
            error = "Username is required."
        elif password and password != confirm_password:
            error = "Passwords do not match."
        elif user["must_update_credentials"] and username == user["username"] and not password:
            error = "You must change the username or password before continuing."
        else:
            updates = []
            values = []
            if username != user["username"]:
                updates.append("username = ?")
                values.append(username)
            email_value = email or None
            if email_value != user["email"]:
                updates.append("email = ?")
                values.append(email_value)
            if password:
                updates.append("password_hash = ?")
                values.append(generate_password_hash(password))
            updates.append("must_update_credentials = 0")
            values.append(user["id"])

            if updates:
                try:
                    db = get_db()
                    db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(values))
                    db.commit()
                    session.pop("needs_update", None)
                    return redirect(url_for("index_page"))
                except sqlite3.IntegrityError:
                    error = "That username or email is already in use."
    return render_template(
        "account.html", user=user, error=error, requires_update=user["must_update_credentials"]
    )


@app.route("/api/users", methods=["POST"])
def create_user():
    init_db()
    db = get_db()
    user_count = db.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
    if user_count and session.get("user_id") is None:
        abort(401, "Must be signed in to add new users.")

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    phone_number = (data.get("phone_number") or "").strip()
    country_code = (data.get("country_code") or "").strip()
    force_update = bool(data.get("force_password_change") or data.get("force_update"))

    if not (username and password and phone_number and country_code):
        abort(
            400,
            "Username, password, phone number, and country code are required.",
        )

    password_hash = generate_password_hash(password)
    try:
        cur = db.execute(
            "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials) VALUES (?, ?, ?, ?, ?, ?)",
            (
                email or None,
                username,
                password_hash,
                phone_number,
                country_code,
                int(force_update),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        abort(409, "A user with that username or email already exists.")

    return jsonify({"id": cur.lastrowid, "username": username, "email": email}), 201


@app.route("/api/auth/start", methods=["POST"])
def start_login():
    init_db()
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    password = (data.get("password") or "").strip()
    if not (identifier and password):
        abort(400, "Username/email and password are required.")

    user = get_user_by_identifier(identifier)
    if user is None or not check_password_hash(user["password_hash"], password):
        abort(401, "Invalid credentials.")

    verification = start_phone_verification(user["phone_number"], user["country_code"])
    if not verification.get("success"):
        abort(502, verification.get("message") or "Failed to send verification code.")

    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires = now + LOGIN_TOKEN_TTL
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE expires_at < ?", (now,))
    db.execute(
        "INSERT INTO login_attempts (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user["id"], now, expires),
    )
    db.commit()
    return (
        jsonify(
            {
                "token": token,
                "phone_hint": mask_phone_number(user["phone_number"]),
                "expires_in": LOGIN_TOKEN_TTL,
            }
        ),
        200,
    )


@app.route("/api/auth/verify", methods=["POST"])
def verify_login():
    init_db()
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    code = (data.get("code") or "").strip()
    if not (token and code):
        abort(400, "Token and verification code are required.")

    db = get_db()
    attempt = db.execute(
        "SELECT token, user_id, expires_at, verified FROM login_attempts WHERE token = ?",
        (token,),
    ).fetchone()
    if not attempt:
        abort(400, "Verification session not found.")
    if attempt["verified"]:
        abort(400, "Verification code already used.")
    now = int(time.time())
    if attempt["expires_at"] < now:
        abort(400, "Verification code has expired.")

    user = db.execute(
        "SELECT id, phone_number, country_code FROM users WHERE id = ?",
        (attempt["user_id"],),
    ).fetchone()

    if not user:
        abort(404, "User not found.")

    verification = check_phone_verification(user["phone_number"], user["country_code"], code)
    if not verification.get("success"):
        abort(401, verification.get("message") or "Invalid verification code.")

    db.execute("UPDATE login_attempts SET verified = 1 WHERE token = ?", (token,))
    db.commit()
    session["user_id"] = user["id"]
    needs_update = bool(user["must_update_credentials"])
    if needs_update:
        session["needs_update"] = True
        target = "/account"
    else:
        session.pop("needs_update", None)
        target = "/app"
    return jsonify({"redirect": target})


@app.route("/projects/<project_id>")
@login_required
def project_page(project_id: str):
    init_db()
    project = require_project(project_id)
    return render_template("project.html", project=project)

@app.route("/projects/<project_id>/dashboard")
@login_required
def project_dashboard(project_id: str):
    init_db()
    project = require_project(project_id)
    return render_template("dashboard.html", project=project)

@app.route("/projects/<project_id>/tool/<tool_key>")
@login_required
def project_tool_page(project_id: str, tool_key: str):
    init_db()
    project = require_project(project_id)
    return render_template("tool.html", project=project, tool=tool_key)


@app.route("/api/projects", methods=["GET"])
@login_required
def list_projects():
    init_db()
    db = get_db()
    rows = db.execute("SELECT id, name, description FROM projects ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/projects", methods=["POST"])
@login_required
def create_project():
    init_db()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, "Project name is required.")
    description = (data.get("description") or "").strip()

    db = get_db()
    cur = db.execute(
        "INSERT INTO projects (name, description) VALUES (?, ?)", (name, description)
    )
    db.commit()
    project_id = cur.lastrowid
    return jsonify({"id": project_id, "name": name, "description": description}), 201


@app.route("/api/projects/<project_id>", methods=["GET"])
@login_required
def get_project(project_id: str):
    init_db()
    project = require_project(project_id)
    return jsonify(project)


@app.route("/api/projects/<project_id>/tasks", methods=["GET"])
@login_required
def list_tasks(project_id: str):
    init_db()
    require_project(project_id)
    db = get_db()
    rows = db.execute(
        """
        SELECT id, project_id, title, description, status, due_date, parent_id, resource_id
        FROM tasks
        WHERE project_id = ?
        ORDER BY id
        """,
        (project_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/projects/<project_id>/tasks", methods=["POST"])
@login_required
def create_task(project_id: str):
    init_db()
    require_project(project_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400, "Task title is required.")
    status = (data.get("status") or "todo").strip().lower()
    if status not in {"todo", "in-progress", "done", "later"}:
        status = "todo"
    due_date = (data.get("due_date") or "").strip()
    description = (data.get("description") or "").strip()
    parent_id = data.get("parent_id")
    if parent_id in ("", None):
        parent_id = None
    resource_id = data.get("resource_id")
    if resource_id in ("", None):
        resource_id = None

    db = get_db()
    cur = db.execute(
        "INSERT INTO tasks (project_id, title, description, status, due_date, parent_id, resource_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, title, description, status, due_date, parent_id, resource_id),
    )
    db.commit()
    task_id = cur.lastrowid
    return (
        jsonify(
            {
                "id": task_id,
                "project_id": int(project_id),
                "title": title,
                "description": description,
                "status": status,
                "due_date": due_date,
                "resource_id": resource_id,
                "parent_id": parent_id,
            }
        ),
        201,
    )


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
@login_required
def update_task(task_id: str):
    init_db()
    db = get_db()
    task = db.execute(
        "SELECT id, project_id, title, description, status, due_date, parent_id, resource_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if not task:
        abort(404, "Task not found.")

    data = request.get_json(silent=True) or {}
    if "title" in data:
        new_title = (data.get("title") or "").strip()
        if new_title:
            db.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
    if "status" in data:
        status = (data.get("status") or "").strip().lower()
        if status in {"todo", "in-progress", "done", "later"}:
            db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    if "description" in data:
        description = (data.get("description") or "").strip()
        db.execute("UPDATE tasks SET description = ? WHERE id = ?", (description, task_id))
    if "due_date" in data:
        due_date = (data.get("due_date") or "").strip()
        db.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (due_date, task_id))
    if "parent_id" in data:
        parent_id = data.get("parent_id")
        if parent_id in ("", None):
            parent_id = None
        db.execute("UPDATE tasks SET parent_id = ? WHERE id = ?", (parent_id, task_id))
    if "resource_id" in data:
        resource_id = data.get("resource_id")
        if resource_id in ("", None):
            resource_id = None
        db.execute("UPDATE tasks SET resource_id = ? WHERE id = ?", (resource_id, task_id))

    db.commit()
    updated = db.execute(
        "SELECT id, project_id, title, description, status, due_date, parent_id, resource_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    return jsonify(dict(updated))


@app.route("/api/backlogs/<project_id>", methods=["GET"])
@login_required
def list_backlogs(project_id: str):
    init_db()
    require_project(project_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, project_id, title, priority, status, tags, parent_id, resource_id FROM backlogs WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/backlogs/<project_id>", methods=["POST"])
@login_required
def create_backlog(project_id: str):
    init_db()
    require_project(project_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400, "Title is required.")
    priority = (data.get("priority") or "medium").strip().lower()
    if priority not in {"high", "medium", "low"}:
        priority = "medium"
    status = (data.get("status") or "todo").strip().lower()
    if status not in {"in-progress", "todo", "later"}:
        status = "todo"
    tags = ",".join([t.strip() for t in (data.get("tags") or "").split(",") if t.strip()])
    parent_id = data.get("parent_id")
    if parent_id in ("", None):
        parent_id = None
    resource_id = data.get("resource_id")
    if resource_id in ("", None):
        resource_id = None

    db = get_db()
    cur = db.execute(
        "INSERT INTO backlogs (project_id, title, priority, status, tags, parent_id, resource_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, title, priority, status, tags, parent_id, resource_id),
    )
    db.commit()
    backlog_id = cur.lastrowid
    return (
        jsonify(
            {
                "id": backlog_id,
                "project_id": int(project_id),
                "title": title,
                "priority": priority,
                "status": status,
                "tags": tags,
                "parent_id": parent_id,
                "resource_id": resource_id,
            }
        ),
        201,
    )


@app.route("/api/backlog/<item_id>", methods=["PATCH"])
@login_required
def update_backlog(item_id: str):
    init_db()
    db = get_db()
    row = db.execute(
        "SELECT id, project_id, title, priority, status, tags, parent_id, resource_id FROM backlogs WHERE id = ?",
        (item_id,),
    ).fetchone()
    if not row:
        abort(404, "Backlog item not found.")

    data = request.get_json(silent=True) or {}
    fields = {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if title:
            fields["title"] = title
    if "priority" in data:
        priority = (data.get("priority") or "").strip().lower()
        if priority in {"high", "medium", "low"}:
            fields["priority"] = priority
    if "status" in data:
        status = (data.get("status") or "").strip().lower()
        if status in {"in-progress", "todo", "later"}:
            fields["status"] = status
    if "tags" in data:
        tags = ",".join([t.strip() for t in (data.get("tags") or "").split(",") if t.strip()])
        fields["tags"] = tags
    if "parent_id" in data:
        parent_id = data.get("parent_id")
        if parent_id in ("", None):
            parent_id = None
        fields["parent_id"] = parent_id
    if "resource_id" in data:
        resource_id = data.get("resource_id")
        if resource_id in ("", None):
            resource_id = None
        fields["resource_id"] = resource_id
    if "resource_id" in data:
        resource_id = data.get("resource_id")
        if resource_id in ("", None):
            resource_id = None
        fields["resource_id"] = resource_id

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        db.execute(f"UPDATE backlogs SET {sets} WHERE id = ?", (*fields.values(), item_id))
        db.commit()

    updated = db.execute(
        "SELECT id, project_id, title, priority, status, tags, parent_id, resource_id FROM backlogs WHERE id = ?",
        (item_id,),
    ).fetchone()
    return jsonify(dict(updated))


@app.route("/api/backlog/<item_id>", methods=["DELETE"])
@login_required
def delete_backlog(item_id: str):
    init_db()
    db = get_db()
    exists = db.execute("SELECT id FROM backlogs WHERE id = ?", (item_id,)).fetchone()
    if not exists:
        abort(404, "Backlog item not found.")
    db.execute("DELETE FROM backlogs WHERE id = ?", (item_id,))
    db.commit()
    return "", 204


@app.route("/api/sprints/<project_id>", methods=["GET"])
@login_required
def list_sprints(project_id: str):
    init_db()
    require_project(project_id)
    db = get_db()
    rows = db.execute(
        """
        SELECT id, project_id, name, status, start_date, end_date, velocity, scope_points, done_points, notes
        FROM sprints
        WHERE project_id = ?
        ORDER BY id DESC
        """,
        (project_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sprints/<project_id>", methods=["POST"])
@login_required
def create_sprint(project_id: str):
    init_db()
    require_project(project_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, "Sprint name is required.")
    status = (data.get("status") or "planned").strip().lower()
    if status not in {"planned", "active", "done"}:
        status = "planned"
    start_date = (data.get("start_date") or "").strip()
    end_date = (data.get("end_date") or "").strip()
    velocity = int(data.get("velocity") or 0)
    scope_points = int(data.get("scope_points") or 0)
    done_points = int(data.get("done_points") or 0)
    notes = (data.get("notes") or "").strip()

    db = get_db()
    cur = db.execute(
        """
        INSERT INTO sprints (project_id, name, status, start_date, end_date, velocity, scope_points, done_points, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, name, status, start_date, end_date, velocity, scope_points, done_points, notes),
    )
    db.commit()
    sprint_id = cur.lastrowid
    return (
        jsonify(
            {
                "id": sprint_id,
                "project_id": int(project_id),
                "name": name,
                "status": status,
                "start_date": start_date,
                "end_date": end_date,
                "velocity": velocity,
                "scope_points": scope_points,
                "done_points": done_points,
                "notes": notes,
            }
        ),
        201,
    )


@app.route("/api/sprint/<sprint_id>", methods=["PATCH"])
@login_required
def update_sprint(sprint_id: str):
    init_db()
    db = get_db()
    row = db.execute(
        """
        SELECT id, project_id, name, status, start_date, end_date, velocity, scope_points, done_points, notes
        FROM sprints WHERE id = ?
        """,
        (sprint_id,),
    ).fetchone()
    if not row:
        abort(404, "Sprint not found.")

    data = request.get_json(silent=True) or {}
    fields = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if name:
            fields["name"] = name
    if "status" in data:
        status = (data.get("status") or "").strip().lower()
        if status in {"planned", "active", "done"}:
            fields["status"] = status
    if "start_date" in data:
        fields["start_date"] = (data.get("start_date") or "").strip()
    if "end_date" in data:
        fields["end_date"] = (data.get("end_date") or "").strip()
    if "velocity" in data:
        fields["velocity"] = int(data.get("velocity") or 0)
    if "scope_points" in data:
        fields["scope_points"] = int(data.get("scope_points") or 0)
    if "done_points" in data:
        fields["done_points"] = int(data.get("done_points") or 0)
    if "notes" in data:
        fields["notes"] = (data.get("notes") or "").strip()

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        db.execute(f"UPDATE sprints SET {sets} WHERE id = ?", (*fields.values(), sprint_id))
        db.commit()

    updated = db.execute(
        """
        SELECT id, project_id, name, status, start_date, end_date, velocity, scope_points, done_points, notes
        FROM sprints WHERE id = ?
        """,
        (sprint_id,),
    ).fetchone()
    return jsonify(dict(updated))


@app.route("/api/sprint/<sprint_id>", methods=["DELETE"])
@login_required
def delete_sprint(sprint_id: str):
    init_db()
    db = get_db()
    exists = db.execute("SELECT id FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if not exists:
        abort(404, "Sprint not found.")
    db.execute("DELETE FROM sprints WHERE id = ?", (sprint_id,))
    db.commit()
    return "", 204


@app.route("/api/resources/<project_id>", methods=["GET"])
@login_required
def list_resources(project_id: str):
    init_db()
    require_project(project_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, project_id, name, status, notes FROM resources WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/resources/<project_id>", methods=["POST"])
@login_required
def create_resource(project_id: str):
    init_db()
    require_project(project_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, "Resource name is required.")
    status = (data.get("status") or "free").strip().lower()
    if status not in {"free", "overloaded", "holiday"}:
        status = "free"
    notes = (data.get("notes") or "").strip()
    db = get_db()
    cur = db.execute(
        "INSERT INTO resources (project_id, name, status, notes) VALUES (?, ?, ?, ?)",
        (project_id, name, status, notes),
    )
    db.commit()
    resource_id = cur.lastrowid
    return jsonify({"id": resource_id, "project_id": int(project_id), "name": name, "status": status, "notes": notes}), 201


@app.route("/api/resource/<resource_id>", methods=["PATCH"])
@login_required
def update_resource(resource_id: str):
    init_db()
    db = get_db()
    row = db.execute(
        "SELECT id, project_id, name, status, notes FROM resources WHERE id = ?", (resource_id,)
    ).fetchone()
    if not row:
        abort(404, "Resource not found.")

    data = request.get_json(silent=True) or {}
    fields = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if name:
            fields["name"] = name
    if "status" in data:
        status = (data.get("status") or "").strip().lower()
        if status in {"free", "overloaded", "holiday"}:
            fields["status"] = status
    if "notes" in data:
        fields["notes"] = (data.get("notes") or "").strip()

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        db.execute(f"UPDATE resources SET {sets} WHERE id = ?", (*fields.values(), resource_id))
        db.commit()

    updated = db.execute(
        "SELECT id, project_id, name, status, notes FROM resources WHERE id = ?", (resource_id,)
    ).fetchone()
    return jsonify(dict(updated))


@app.route("/api/resource/<resource_id>", methods=["DELETE"])
@login_required
def delete_resource(resource_id: str):
    init_db()
    db = get_db()
    exists = db.execute("SELECT id FROM resources WHERE id = ?", (resource_id,)).fetchone()
    if not exists:
        abort(404, "Resource not found.")
    db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    db.commit()
    return "", 204

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id: str):
    init_db()
    db = get_db()
    exists = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not exists:
        abort(404, "Task not found.")
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    return "", 204


if __name__ == "__main__":
    with app.app_context():
        init_db()
    port = int(os.environ.get("PORT", "51001") or "51001")
    app.run(host="0.0.0.0", port=port, debug=True)


