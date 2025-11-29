import os
import sys
import sqlite3

# Guard: require explicit confirmation via env var or CLI flag
CONFIRM_ENV = os.environ.get("CONFIRM_USER_PURGE", "").lower() in {"1", "true", "yes"}
CONFIRM_FLAG = any(arg in {"--confirm", "-y"} for arg in sys.argv[1:])

if not (CONFIRM_ENV or CONFIRM_FLAG):
    print("Refusing to delete users. Re-run with --confirm or set CONFIRM_USER_PURGE=1.")
    sys.exit(2)

# Reuse app's DB location logic without starting server
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    import app  # noqa: F401
except Exception as e:
    print(f"Failed to load app module: {e}")
    sys.exit(1)

DB_PATH = app.DB_PATH

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    sys.exit(1)

try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Disable foreign key constraints if present to allow cascade-like behavior
    cur.execute("PRAGMA foreign_keys = OFF;")
    # Wipe all users
    cur.execute("DELETE FROM users;")
    conn.commit()
    print("All users deleted.")
except Exception as e:
    print(f"Error deleting users: {e}")
    sys.exit(1)
finally:
    try:
        conn.close()
    except Exception:
        pass
