import sqlite3
from flask import Flask, request, redirect, url_for, render_template_string

# ================= 配置 =================
DB_PATH = "fields.db"
TXT_PATH = "atomic_structure.txt"

app = Flask(__name__)

# ================= 数据库 =================
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS atomic_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """)
        # 初始化默认条目（只在第一次运行时插入）
        if c.execute("SELECT COUNT(*) FROM atomic_fields").fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO atomic_fields(name) VALUES(?)",
                [("知识本身",), ("原文片段",), ("原文出处",), ("用户新增内容",)]
            )

# ================= 前端 =================
HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>原子知识结构编辑</title>

<style>
:root {
  --bg:#f6f7fb;
  --card:#ffffff;
  --border:#e5e7eb;
  --text:#1f2937;
  --muted:#6b7280;
  --primary:#4f46e5;
  --danger:#ef4444;
  --save:#10b981;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  font-family: -apple-system, BlinkMacSystemFont,
               "Segoe UI", Roboto, Helvetica, Arial;
  color: var(--text);
}

.wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card {
  width: 420px;
  background: var(--card);
  border-radius: 18px;
  box-shadow:
    0 10px 30px rgba(0,0,0,.08),
    0 1px 4px rgba(0,0,0,.04);
  padding: 24px 22px 20px;
}

h2 {
  margin: 0;
  font-size: 20px;
}

.subtitle {
  font-size: 13px;
  color: var(--muted);
  margin: 6px 0 18px;
}

.item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 10px;
  transition: all .15s ease;
}

.item:hover {
  border-color: var(--primary);
}

.item-name {
  font-size: 14px;
}

.delete-btn {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 16px;
  cursor: pointer;
  opacity: 0;
}

.item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: var(--danger);
}

.add-box {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.add-row {
  display: flex;
  gap: 8px;
}

.add-row input {
  flex: 1;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  font-size: 14px;
}

.add-row button {
  padding: 10px 14px;
  border-radius: 10px;
  border: none;
  background: var(--primary);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

.save-btn {
  width: 100%;
  margin-top: 16px;
  padding: 11px;
  border-radius: 12px;
  border: none;
  background: var(--save);
  color: white;
  font-size: 14px;
  cursor: pointer;
}
</style>
</head>

<body>
<div class="wrapper">
  <div class="card">
    <h2>原子知识结构</h2>
    <div class="subtitle">定义原子知识由哪些条目组成</div>

    {% for f in fields %}
    <div class="item">
      <div class="item-name">{{ f.name }}</div>
      <form method="post" action="/delete/{{ f.id }}">
        <button class="delete-btn" type="submit">✕</button>
      </form>
    </div>
    {% endfor %}

    <div class="add-box">
      <form method="post" action="/add" class="add-row">
        <input type="text" name="name" placeholder="输入新条目名称" required>
        <button type="submit">添加</button>
      </form>
    </div>

    <form method="post" action="/save">
      <button type="submit" class="save-btn">💾 保存</button>
    </form>

  </div>
</div>
</body>
</html>
"""

# ================= 路由 =================
@app.route("/")
def index():
    with conn() as c:
        fields = c.execute(
            "SELECT * FROM atomic_fields ORDER BY id"
        ).fetchall()
    return render_template_string(HTML, fields=fields)

@app.route("/add", methods=["POST"])
def add():
    name = request.form["name"].strip()
    if name:
        try:
            with conn() as c:
                c.execute(
                    "INSERT INTO atomic_fields(name) VALUES(?)",
                    (name,)
                )
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for("index"))

@app.route("/delete/<int:fid>", methods=["POST"])
def delete(fid):
    with conn() as c:
        c.execute("DELETE FROM atomic_fields WHERE id=?", (fid,))
    return redirect(url_for("index"))

@app.route("/save", methods=["POST"])
def save():
    with conn() as c:
        rows = c.execute(
            "SELECT name FROM atomic_fields ORDER BY id"
        ).fetchall()

    with open(TXT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["name"] + "\n")

    return redirect(url_for("index"))

# ================= 启动 =================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
