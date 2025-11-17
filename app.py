import os
import sqlite3
from flask import Flask, render_template, request, jsonify, abort, g

app = Flask(__name__)

# Location for the SQLite file; override PROJECT_DATA_DIR to move it to a writable path on the server.
DATA_DIR = os.environ.get("PROJECT_DATA_DIR") or app.instance_path
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILENAME = os.environ.get("PROJECT_DB", "project_manager.sqlite")
DB_PATH = os.path.join(DATA_DIR, DB_FILENAME)


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


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


@app.route("/")
def index():
    init_db()
    return render_template("index.html")


@app.route("/projects/<project_id>")
def project_page(project_id: str):
    init_db()
    project = require_project(project_id)
    return render_template("project.html", project=project)


@app.route("/api/projects", methods=["GET"])
def list_projects():
    init_db()
    db = get_db()
    rows = db.execute("SELECT id, name, description FROM projects ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/projects", methods=["POST"])
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
def get_project(project_id: str):
    init_db()
    project = require_project(project_id)
    return jsonify(project)


@app.route("/api/projects/<project_id>/tasks", methods=["GET"])
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
    app.run(host="0.0.0.0", debug=True)


