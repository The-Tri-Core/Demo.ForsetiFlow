import sys, sqlite3, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app
conn = sqlite3.connect(app.DB_PATH)
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM users')
print(cur.fetchone()[0])
conn.close()
