import base64
import io
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import datetime
import pyotp
import qrcode
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import Flask, render_template, request, jsonify, abort, g, session, redirect, url_for
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-secret-key"

oauth = OAuth()
oauth.init_app(app)

# oauth configuration for single sign-on providers
OAUTH_PROVIDER_CONFIG = {
    "google": {
        "display_name": "Google",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "scope": "openid email profile",
    },
    "microsoft": {
        "display_name": "Microsoft",
        "client_id_env": "MICROSOFT_CLIENT_ID",
        "client_secret_env": "MICROSOFT_CLIENT_SECRET",
        "server_metadata_url": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        "scope": "openid email profile User.Read",
    },
}
AUTHENTIK_BASE_URL = os.environ.get("AUTHENTIK_BASE_URL")
if AUTHENTIK_BASE_URL:
    base = AUTHENTIK_BASE_URL.rstrip("/")
    OAUTH_PROVIDER_CONFIG["authentik"] = {
        "display_name": "Authentik",
        "client_id_env": "AUTHENTIK_CLIENT_ID",
        "client_secret_env": "AUTHENTIK_CLIENT_SECRET",
        "server_metadata_url": f"{base}/application/o/.well-known/openid-configuration",
        "scope": "openid email profile",
    }
AVAILABLE_OAUTH_PROVIDERS = []


def _register_oauth_providers():
    for name, spec in OAUTH_PROVIDER_CONFIG.items():
        client_id = os.environ.get(spec["client_id_env"])
        client_secret = os.environ.get(spec["client_secret_env"])
        if not (client_id and client_secret):
            continue
        client_kwargs = {"scope": spec["scope"]}
        client_kwargs.update(spec.get("client_kwargs", {}))
        oauth.register(
            name=name,
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=spec["server_metadata_url"],
            client_kwargs=client_kwargs,
        )
        AVAILABLE_OAUTH_PROVIDERS.append(
            {"name": name, "display_name": spec["display_name"]}
        )


_register_oauth_providers()

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

DEFAULT_ADMIN_USERNAME = os.environ.get("DEFAULT_ADMIN_USERNAME") or "forseti"
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD") or "flow"
DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL")
DEFAULT_ADMIN_PHONE = os.environ.get("DEFAULT_ADMIN_PHONE") or "0000000000"
DEFAULT_ADMIN_COUNTRY = os.environ.get("DEFAULT_ADMIN_COUNTRY") or "1"
MFA_ISSUER = os.environ.get("MFA_ISSUER") or "Forseti Flow"

# Demo mode configuration: when enabled, the normal TOTP secret provisioning and
# verification are bypassed in favor of a single fixed code suitable for a
# public showcase (non-production). The database is automatically reset every 24h.
DEMO_MODE = os.environ.get("DEMO_MODE", "0") not in {"0", "false", "False"}
DEMO_TOTP_CODE = os.environ.get("DEMO_TOTP_CODE", "246810").strip()


def _get_or_create_demo_user() -> int:
    """Ensure there is at least one demo user and return its id."""
    db = get_db()
    row = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    db.execute(
        "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials, is_admin, mfa_secret) VALUES (?, ?, ?, ?, ?, 0, 1, '')",
        (None, DEFAULT_ADMIN_USERNAME, "", "", ""),
    )
    db.commit()
    row = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    return row["id"]


def _reset_database():
    """Delete and re-initialize the SQLite database (demo mode)."""
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except OSError:
        pass
    with app.app_context():
        init_db()


def _needs_daily_reset() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    age_seconds = time.time() - os.path.getmtime(DB_PATH)
    return age_seconds > 60 * 60 * 24  # 24h


def _maybe_reset_database_for_demo():
    if DEMO_MODE and _needs_daily_reset():
        _reset_database()


def _schedule_daily_reset():
    if not DEMO_MODE:
        return
    def worker():
        while True:
            now = datetime.datetime.utcnow()
            tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            delay = (tomorrow - now).total_seconds()
            time.sleep(max(delay, 60))  # minimum sleep safeguard
            _reset_database()
    threading.Thread(target=worker, name="daily-reset", daemon=True).start()


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


def _normalize_username(raw: str) -> str:
    candidate = "".join(
        ch for ch in (raw or "").strip().lower() if ch.isalnum() or ch in {"_", "-", "."}
    )
    return candidate or "user"


def _generate_unique_username(base: str) -> str:
    db = get_db()
    username = base
    suffix = 1
    while True:
        exists = db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if not exists:
            return username
        username = f"{base}{suffix}"
        suffix += 1


def _create_user_from_oauth(email: str, display_name: str):
    db = get_db()
    base_username = _normalize_username(display_name or email.split("@")[0] or "user")
    username = _generate_unique_username(base_username)
    password_hash = generate_password_hash(secrets.token_urlsafe(64))
    try:
        cur = db.execute(
            "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials, is_admin) VALUES (?, ?, ?, ?, ?, 0, 0)",
            (email, username, password_hash, "", ""),
        )
        db.commit()
        inserted_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return get_user_by_identifier(email)
    return db.execute(
        """
        SELECT id, email, username, phone_number, country_code, must_update_credentials
        FROM users WHERE id = ?
        """,
        (inserted_id,),
    ).fetchone()


def _extract_oauth_user_info(client, token: dict) -> dict:
    user_info = None
    if token.get("id_token"):
        try:
            user_info = client.parse_id_token(token)
        except (OAuthError, ValueError):
            user_info = None
    if not user_info:
        try:
            resp = client.get("userinfo")
            resp.raise_for_status()
            user_info = resp.json()
        except Exception:
            user_info = None
    if isinstance(user_info, dict):
        return user_info
    return {}


def _is_oauth_provider_enabled(provider_name: str) -> bool:
    return any(p["name"] == provider_name for p in AVAILABLE_OAUTH_PROVIDERS)


def _get_available_oauth_providers() -> list[dict]:
    return list(AVAILABLE_OAUTH_PROVIDERS)


def _get_user_count() -> int:
    db = get_db()
    row = db.execute("SELECT COUNT(*) as total FROM users").fetchone()
    return row["total"] if row else 0


@app.context_processor
def inject_demo_flags():
    return {
        "demo_mode": DEMO_MODE,
        "demo_code": DEMO_TOTP_CODE if DEMO_MODE else "",
    }


def _generate_mfa_qr(secret: str, label: str) -> str:
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=label[:64], issuer_name=MFA_ISSUER)
    qr = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _ensure_default_user(db):
    # Default bootstrap user is no longer needed; keep as no-op.
    return


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
            is_admin INTEGER NOT NULL DEFAULT 0,
            mfa_secret TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN mfa_secret TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("UPDATE users SET must_update_credentials = 0 WHERE must_update_credentials IS NULL")
    except sqlite3.OperationalError:
        pass
    db.commit()
    _ensure_default_user(db)
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
        SELECT id, email, username, password_hash, phone_number, country_code, must_update_credentials, mfa_secret
        FROM users
        WHERE username = ? OR (email IS NOT NULL AND LOWER(email) = LOWER(?))
        """,
        (identifier, identifier),
    ).fetchone()


def get_user_by_id(user_id: int):
    db = get_db()
    return db.execute(
        """
        SELECT id, email, username, phone_number, country_code, must_update_credentials, mfa_secret
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def render_login_view():
    init_db()
    oauth_error = session.pop("oauth_error", None)
    allow_registration = _get_user_count() == 0
    # If no users exist, generate a pending MFA secret and QR for setup
    pending_mfa_secret = session.get("pending_mfa_secret")
    if allow_registration and not pending_mfa_secret:
        pending_mfa_secret = pyotp.random_base32()
        session["pending_mfa_secret"] = pending_mfa_secret
    mfa_qr = None
    if allow_registration and pending_mfa_secret:
        label = DEFAULT_ADMIN_USERNAME
        mfa_qr = _generate_mfa_qr(pending_mfa_secret, label)
    return render_template(
        "login.html",
        oauth_providers=_get_available_oauth_providers(),
        oauth_error=oauth_error,
        allow_registration=allow_registration,
        mfa_qr=mfa_qr,
    )


@app.route("/")
@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index_page"))
    if DEMO_MODE:
        # In demo mode, always show login page with demo code hint.
        return render_template(
            "login.html",
            oauth_providers=[],
            oauth_error=None,
            allow_registration=False,
            mfa_qr=None,
            demo_code=DEMO_TOTP_CODE,
        )
    if _get_user_count() == 0:
        return redirect(url_for("setup_page"))
    return render_login_view()

@app.route("/setup")
def setup_page():
    init_db()
    if DEMO_MODE or _get_user_count():
        return redirect(url_for("login_page"))
    # Ensure a pending secret and QR are available
    pending_mfa_secret = session.get("pending_mfa_secret")
    if not pending_mfa_secret:
        pending_mfa_secret = pyotp.random_base32()
        session["pending_mfa_secret"] = pending_mfa_secret
    mfa_qr = _generate_mfa_qr(pending_mfa_secret, DEFAULT_ADMIN_USERNAME)
    return render_template("setup.html", mfa_qr=mfa_qr)


@app.route("/register", methods=["GET", "POST"])
def register_page():
    init_db()
    if _get_user_count():
        return redirect(url_for("login_page"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()
        phone_number = (request.form.get("phone_number") or "").strip()
        country_code = (request.form.get("country_code") or "").strip()

        if not username:
            error = "Username is required."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif not (password and phone_number and country_code):
            error = "Password, phone number, and country code are required."
        else:
            password_hash = generate_password_hash(password)
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials, is_admin) VALUES (?, ?, ?, ?, ?, 0, 1)",
                    (email or None, username, password_hash, phone_number, country_code),
                )
                db.commit()
                user = get_user_by_id(cur.lastrowid)
                if user:
                    session["user_id"] = user["id"]
                    session.pop("needs_update", None)
                    return redirect("/app")
                error = "Failed to create user."
            except sqlite3.IntegrityError:
                error = "That username or email is already in use."
    return render_template("register.html", error=error)


@app.route("/app")
@login_required
def index_page():
    init_db()
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login_page"))


@app.route("/login/oauth/<provider>")
def oauth_login(provider: str):
    if not _is_oauth_provider_enabled(provider):
        abort(404)
    client = oauth.create_client(provider)
    if client is None:
        abort(404)
    redirect_uri = url_for("oauth_callback", provider=provider, _external=True)
    return client.authorize_redirect(redirect_uri)


@app.route("/auth/oauth/<provider>/callback")
def oauth_callback(provider: str):
    if not _is_oauth_provider_enabled(provider):
        abort(404)
    client = oauth.create_client(provider)
    if client is None:
        abort(404)
    try:
        token = client.authorize_access_token()
    except OAuthError as exc:
        session["oauth_error"] = str(exc)
        return redirect(url_for("login_page"))
    except Exception:
        session["oauth_error"] = "Unable to complete the external authentication flow."
        return redirect(url_for("login_page"))

    init_db()
    user_info = _extract_oauth_user_info(client, token)
    email = (user_info.get("email") or "").strip().lower()
    if not email:
        session["oauth_error"] = "External provider did not supply an email address."
        return redirect(url_for("login_page"))

    user = get_user_by_identifier(email)
    if user is None:
        user = _create_user_from_oauth(email, user_info.get("name") or user_info.get("preferred_username") or "")
    if not user:
        session["oauth_error"] = "Unable to create or load a user account."
        return redirect(url_for("login_page"))

    session["user_id"] = user["id"]
    if user["must_update_credentials"]:
        session["needs_update"] = True
        return redirect("/account")
    session.pop("needs_update", None)
    return redirect("/app")


@app.route("/account", methods=["GET", "POST"])
@login_required
def account_page():
    user = get_user_by_id(session["user_id"])
    if not user:
        abort(404, "User not found.")
    error = None
    mfa_setup_required = False if DEMO_MODE else not bool(user["mfa_secret"])
    pending_mfa_secret = session.get("pending_mfa_secret")
    if not mfa_setup_required and "pending_mfa_secret" in session:
        session.pop("pending_mfa_secret", None)
        pending_mfa_secret = None
    if mfa_setup_required and not pending_mfa_secret:
        pending_mfa_secret = pyotp.random_base32()
        session["pending_mfa_secret"] = pending_mfa_secret
    mfa_qr = None
    if mfa_setup_required and pending_mfa_secret:
        label = (user["email"] or user["username"] or DEFAULT_ADMIN_USERNAME)
        mfa_qr = _generate_mfa_qr(pending_mfa_secret, label)
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        totp_code = (request.form.get("totp_code") or "").strip()

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

            mfa_ready = True
            if mfa_setup_required:
                if not pending_mfa_secret:
                    error = "Unable to generate an authenticator secret. Reload the page and try again."
                    mfa_ready = False
                elif not totp_code:
                    error = "Enter the authenticator code from your authenticator app."
                    mfa_ready = False
                elif not pyotp.TOTP(pending_mfa_secret).verify(totp_code, valid_window=1):
                    error = "Invalid authenticator code."
                    mfa_ready = False
                else:
                    updates.append("mfa_secret = ?")
                    values.append(pending_mfa_secret)
            if updates and mfa_ready:
                try:
                    db = get_db()
                    db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(values))
                    db.commit()
                    session.pop("needs_update", None)
                    session.pop("pending_mfa_secret", None)
                    return redirect(url_for("index_page"))
                except sqlite3.IntegrityError:
                    error = "That username or email is already in use."
    return render_template(
        "account.html",
        user=user,
        error=error,
        requires_update=user["must_update_credentials"],
        mfa_setup_required=mfa_setup_required,
        mfa_qr=mfa_qr,
        mfa_secret=pending_mfa_secret,
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
    custom_force = bool(data.get("force_password_change") or data.get("force_update"))
    is_first_user = user_count == 0
    force_update = False if is_first_user else custom_force
    is_admin = 1 if is_first_user else 0

    if not (username and password and phone_number and country_code):
        abort(
            400,
            "Username, password, phone number, and country code are required.",
        )

    password_hash = generate_password_hash(password)
    try:
        cur = db.execute(
            "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials, is_admin) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                email or None,
                username,
                password_hash,
                phone_number,
                country_code,
                int(force_update),
                is_admin,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        abort(409, "A user with that username or email already exists.")

    return jsonify({"id": cur.lastrowid, "username": username, "email": email}), 201


@app.route("/api/auth/start", methods=["POST"])
def start_login():
    init_db()
    # Deprecated: password-based login removed. Keep endpoint but fail clearly.
    abort(400, "Password login is disabled. Use TOTP-only login.")

@app.route("/api/auth/totp-login", methods=["POST"])
def totp_login():
    init_db()
    data = request.get_json(silent=True) or {}
    totp_code = (data.get("totp_code") or "").strip()
    if not totp_code:
        abort(400, "Authenticator code is required.")
    if DEMO_MODE:
        if totp_code != DEMO_TOTP_CODE:
            abort(401, "Invalid demo code.")
        session["user_id"] = _get_or_create_demo_user()
        session.pop("needs_update", None)
        return jsonify({"redirect": "/app"})
    db = get_db()
    row = db.execute("SELECT id, mfa_secret, must_update_credentials FROM users ORDER BY id LIMIT 1").fetchone()
    if not row:
        abort(404, "No user configured. Set up the authenticator first.")
    secret = row["mfa_secret"] or ""
    if not secret:
        abort(409, "Authenticator not configured. Open the account page to set it up.")
    totp = pyotp.TOTP(secret)
    if not totp.verify(totp_code, valid_window=1):
        abort(401, "Invalid authenticator code.")
    session["user_id"] = row["id"]
    if bool(row["must_update_credentials"]):
        session["needs_update"] = True
        target = "/account"
    else:
        session.pop("needs_update", None)
        target = "/app"
    return jsonify({"redirect": target})

@app.route("/api/auth/setup-first", methods=["POST"])
def setup_first_user():
    init_db()
    db = get_db()
    count = db.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
    if DEMO_MODE:
        # In demo mode the first user is auto-created with the demo code.
        data = request.get_json(silent=True) or {}
        totp_code = (data.get("totp_code") or "").strip()
        if totp_code != DEMO_TOTP_CODE:
            abort(401, "Invalid demo code.")
        user_id = _get_or_create_demo_user()
        session["user_id"] = user_id
        return jsonify({"redirect": "/app"})
    if count:
        abort(409, "User already exists.")
    data = request.get_json(silent=True) or {}
    totp_code = (data.get("totp_code") or "").strip()
    pending_secret = session.get("pending_mfa_secret") or ""
    if not pending_secret:
        # Generate and hold a secret for setup flow
        pending_secret = pyotp.random_base32()
        session["pending_mfa_secret"] = pending_secret
        abort(409, "Setup secret generated. Refresh and scan the QR, then submit the code.")
    if not totp_code:
        abort(400, "Enter the authenticator code from your app.")
    if not pyotp.TOTP(pending_secret).verify(totp_code, valid_window=1):
        abort(401, "Invalid authenticator code.")
    # Create a single admin user with no password requirements
    db.execute(
        "INSERT INTO users (email, username, password_hash, phone_number, country_code, must_update_credentials, is_admin, mfa_secret) VALUES (?, ?, ?, ?, ?, 0, 1, ?)",
        (None, DEFAULT_ADMIN_USERNAME, "", "", "", pending_secret),
    )
    db.commit()
    user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    session["user_id"] = user["id"]
    session.pop("pending_mfa_secret", None)
    return jsonify({"redirect": "/app"})


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
        SELECT id, project_id, title, description, status, due_date, parent_id
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
    # Single-user mode: ignore assignee/resource

    db = get_db()
    cur = db.execute(
        "INSERT INTO tasks (project_id, title, description, status, due_date, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, title, description, status, due_date, parent_id),
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
        "SELECT id, project_id, title, description, status, due_date, parent_id FROM tasks WHERE id = ?",
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
    # Ignore resource updates in single-user mode

    db.commit()
    updated = db.execute(
        "SELECT id, project_id, title, description, status, due_date, parent_id FROM tasks WHERE id = ?",
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
        "SELECT id, project_id, title, priority, status, tags, parent_id FROM backlogs WHERE project_id = ? ORDER BY id DESC",
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
    # Single-user mode: ignore assignee/resource

    db = get_db()
    cur = db.execute(
        "INSERT INTO backlogs (project_id, title, priority, status, tags, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, title, priority, status, tags, parent_id),
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
        "SELECT id, project_id, title, priority, status, tags, parent_id FROM backlogs WHERE id = ?",
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
    # Ignore resource updates in single-user mode

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        db.execute(f"UPDATE backlogs SET {sets} WHERE id = ?", (*fields.values(), item_id))
        db.commit()

    updated = db.execute(
        "SELECT id, project_id, title, priority, status, tags, parent_id FROM backlogs WHERE id = ?",
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
        _maybe_reset_database_for_demo()
        _schedule_daily_reset()
    port = int(os.environ.get("PORT", "51005") or "51005")
    app.run(host="0.0.0.0", port=port, debug=True)


