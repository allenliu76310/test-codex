from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import secrets
import sqlite3
import urllib.parse
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
ADMIN_ID = "ADMIN"
ADMIN_PASSWORD_HASH = hashlib.sha256("admin123".encode("utf-8")).hexdigest()
SESSIONS: dict[str, dict[str, str]] = {}


def hash_password(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL UNIQUE,
                employee_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('employee', 'admin')) DEFAULT 'employee',
                password_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                employee_name TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('check-in', 'check-out')),
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_employee_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_record_id INTEGER NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # 舊版資料庫升級：補 password_hash 欄位
        columns = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "password_hash" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")

        conn.execute(
            """
            INSERT OR IGNORE INTO users (employee_id, employee_name, role, password_hash)
            VALUES (?, ?, 'admin', ?)
            """,
            (ADMIN_ID, "系統管理員", ADMIN_PASSWORD_HASH),
        )


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _build_filters(employee_id: str = "", date: str = "") -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if employee_id:
        clauses.append("employee_id = ?")
        params.append(employee_id)
    if date:
        clauses.append("substr(created_at, 1, 10) = ?")
        params.append(date)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def fetch_latest(limit: int = 50, employee_id: str = "", date: str = "") -> list[sqlite3.Row]:
    where_sql, params = _build_filters(employee_id, date)
    with get_db_connection() as conn:
        return conn.execute(
            f"""
            SELECT id, employee_id, employee_name, event_type, created_at
            FROM attendance {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()


def fetch_all(employee_id: str = "", date: str = "") -> list[sqlite3.Row]:
    where_sql, params = _build_filters(employee_id, date)
    with get_db_connection() as conn:
        return conn.execute(
            f"""
            SELECT id, employee_id, employee_name, event_type, created_at
            FROM attendance {where_sql}
            ORDER BY id DESC
            """,
            params,
        ).fetchall()


def fetch_users() -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT employee_id, employee_name, role FROM users ORDER BY employee_id"
        ).fetchall()


def fetch_employee_list() -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT employee_id, employee_name FROM users WHERE role = 'employee' ORDER BY employee_id"
        ).fetchall()


def fetch_audit_logs(limit: int = 100) -> list[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            """
            SELECT admin_employee_id, action, target_record_id, old_value, new_value, created_at
            FROM admin_audit_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_user_by_employee_id(employee_id: str) -> sqlite3.Row | None:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT employee_id, employee_name, role, password_hash FROM users WHERE employee_id = ?",
            (employee_id,),
        ).fetchone()


def get_latest_event_type(employee_id: str) -> str | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT event_type FROM attendance WHERE employee_id = ? ORDER BY id DESC LIMIT 1",
            (employee_id,),
        ).fetchone()
        return row[0] if row else None


def insert_or_update_employee(employee_id: str, employee_name: str, raw_password: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (employee_id, employee_name, role, password_hash)
            VALUES (?, ?, 'employee', ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                employee_name = excluded.employee_name,
                password_hash = excluded.password_hash,
                role = 'employee'
            """,
            (employee_id, employee_name, hash_password(raw_password)),
        )


def update_user(employee_id: str, employee_name: str, role: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET employee_name = ?, role = ? WHERE employee_id = ?",
            (employee_name, role, employee_id),
        )


def insert_record(employee_id: str, employee_name: str, event_type: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO attendance (employee_id, employee_name, event_type, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (employee_id, employee_name, event_type, timestamp),
        )


def verify_employee_credentials(employee_id: str, raw_password: str) -> sqlite3.Row | None:
    user = get_user_by_employee_id(employee_id)
    if not user or user["role"] != "employee":
        return None
    if user["password_hash"] != hash_password(raw_password):
        return None
    return user


def update_attendance_record(
    record_id: int, employee_id: str, employee_name: str, event_type: str, created_at: str
) -> tuple[dict, dict] | None:
    with get_db_connection() as conn:
        old = conn.execute("SELECT * FROM attendance WHERE id = ?", (record_id,)).fetchone()
        if not old:
            return None
        old_data = dict(old)
        conn.execute(
            """
            UPDATE attendance
            SET employee_id = ?, employee_name = ?, event_type = ?, created_at = ?
            WHERE id = ?
            """,
            (employee_id, employee_name, event_type, created_at, record_id),
        )
        new = conn.execute("SELECT * FROM attendance WHERE id = ?", (record_id,)).fetchone()
        return old_data, dict(new)


def insert_audit_log(
    admin_employee_id: str, action: str, target_record_id: int, old_value: dict, new_value: dict
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO admin_audit_logs (admin_employee_id, action, target_record_id, old_value, new_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                admin_employee_id,
                action,
                target_record_id,
                json.dumps(old_value, ensure_ascii=False),
                json.dumps(new_value, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def create_session(role: str, employee_id: str, employee_name: str) -> str:
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = {
        "role": role,
        "employee_id": employee_id,
        "employee_name": employee_name,
    }
    return token


class AttendanceHandler(BaseHTTPRequestHandler):
    def _parse_session(self) -> dict[str, str] | None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        token = cookie.get("session_token")
        if not token:
            return None
        return SESSIONS.get(token.value)

    def _redirect(self, location: str, session_token: str | None = None, clear_session: bool = False) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if session_token:
            self.send_header("Set-Cookie", f"session_token={session_token}; Path=/; HttpOnly")
        if clear_session:
            self.send_header("Set-Cookie", "session_token=; Path=/; Max-Age=0; HttpOnly")
        self.end_headers()

    def _redirect_with_msg(self, message: str) -> None:
        self._redirect(f"/?msg={urllib.parse.quote(message)}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        session = self._parse_session()

        if parsed.path == "/login":
            self._render_login(parsed.query)
            return

        if parsed.path == "/kiosk":
            self._render_kiosk(parsed.query)
            return

        if parsed.path == "/logout":
            if session:
                token = SimpleCookie(self.headers.get("Cookie")).get("session_token")
                if token and token.value in SESSIONS:
                    SESSIONS.pop(token.value, None)
            self._redirect(f"/login?msg={urllib.parse.quote('已登出')}", clear_session=True)
            return

        if not session:
            self._redirect(f"/login?msg={urllib.parse.quote('請先登入')}")
            return

        if parsed.path == "/":
            self._render_index(parsed.query, session)
            return

        if parsed.path == "/admin/employees":
            self._render_employee_directory(parsed.query, session)
            return

        if parsed.path == "/api/records":
            self._render_records_json(parsed.query, session)
            return

        if parsed.path == "/export.xls":
            self._render_records_excel(parsed.query, session)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form_data = urllib.parse.parse_qs(body)

        if parsed.path == "/login":
            self._handle_login(form_data)
            return

        if parsed.path == "/kiosk/clock":
            self._handle_kiosk_clock(form_data)
            return

        session = self._parse_session()
        if not session:
            self._redirect(f"/login?msg={urllib.parse.quote('請先登入')}")
            return

        if parsed.path == "/clock":
            self._handle_clock(form_data, session)
            return

        if parsed.path == "/admin/employee/create":
            self._handle_admin_employee_create(form_data, session)
            return

        if parsed.path == "/admin/user/update":
            self._handle_admin_user_update(form_data, session)
            return

        if parsed.path == "/admin/attendance/update":
            self._handle_admin_attendance_update(form_data, session)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _render_login(self, query_string: str) -> None:
        query = urllib.parse.parse_qs(query_string)
        message = html.escape(query.get("msg", [""])[0])
        html_content = f"""<!doctype html>
<html lang=\"zh-Hant\"><head><meta charset=\"UTF-8\"/><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>
<title>登入 - 員工打卡系統</title>
<style>
body {{ font-family: Arial, sans-serif; background:#f3f6fb; }}
.card {{ max-width: 560px; margin: 50px auto; background:#fff; padding:20px; border-radius:12px; box-shadow:0 4px 14px rgba(0,0,0,.08); }}
input, select, button {{ width:100%; padding:10px; margin:6px 0; border-radius:8px; border:1px solid #c7d2e2; }}
button {{ background:#1f6feb; color:#fff; border:none; }}
.hint {{ background:#eef6ff; padding:10px; border-radius:8px; margin:8px 0; }}
</style></head>
<body><div class=\"card\"><h1>後台登入</h1>
<p>管理員帳號固定為 <b>ADMIN</b>，預設密碼 <b>admin123</b>。</p>
<p>員工若只要打卡，請前往 <a href=\"/kiosk\">員工打卡頁面</a>。</p>
{f'<div class="hint">{message}</div>' if message else ''}
<form method=\"post\" action=\"/login\">
<select name=\"role\" required><option value=\"employee\">員工</option><option value=\"admin\">管理員</option></select>
<input type=\"text\" name=\"employee_id\" placeholder=\"員工編號\" required />
<input type=\"text\" name=\"employee_name\" placeholder=\"員工姓名（首次員工登入可填）\" />
<input type=\"password\" name=\"password\" placeholder=\"密碼\" />
<button type=\"submit\">登入</button>
</form></div></body></html>"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _render_kiosk(self, query_string: str) -> None:
        query = urllib.parse.parse_qs(query_string)
        message = html.escape(query.get("msg", [""])[0])
        html_content = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>員工打卡</title>
<style>
body {{ font-family: Arial, sans-serif; background:#f6fbff; }}
.card {{ max-width: 760px; margin: 40px auto; background:#fff; padding:24px; border-radius:14px; box-shadow:0 4px 14px rgba(0,0,0,.08); }}
input, select, button {{ width:100%; margin:8px 0; padding:12px; border-radius:8px; border:1px solid #c7d2e2; font-size:16px; }}
button {{ background:#1f6feb; color:#fff; border:none; font-size:18px; }}
.hint {{ background:#eef6ff; color:#154b8b; padding:10px; border-radius:8px; margin:8px 0; }}
.field label {{ display:block; font-weight:700; margin-top:8px; }}
.field small {{ display:block; color:#5b6470; margin-bottom:4px; }}
.datetime-board {{ background: linear-gradient(135deg, #0f4c81, #1f6feb); color:#fff; border-radius:14px; padding:14px 18px; margin:12px 0 16px; text-align:center; }}
.datetime-date {{ font-size:34px; font-weight:700; }}
.datetime-time {{ font-size:62px; font-weight:800; line-height:1.1; margin-top:4px; font-variant-numeric: tabular-nums; }}
</style></head>
<body><div class="card"><h1>員工打卡</h1>
<p>請輸入員工編號與密碼，系統會自動帶出姓名並顯示打卡結果。</p>
<div class="datetime-board"><div class="datetime-date" id="current-date">--</div><div class="datetime-time" id="current-time">--:--:--</div></div>
{f'<div class="hint">{message}</div>' if message else ''}
<form method="post" action="/kiosk/clock">
<div class="field">
  <label for="employee_id">員工編號（必填）</label>
  <small>請輸入員工編號，例如：001 或 E102</small>
  <input id="employee_id" name="employee_id" placeholder="例如：001" required>
</div>
<div class="field">
  <label for="password">打卡密碼（必填）</label>
  <small>請輸入此員工的打卡密碼</small>
  <input id="password" type="password" name="password" placeholder="請輸入打卡密碼" required>
</div>
<div class="field">
  <label for="event_type">打卡類型（必填）</label>
  <small>請選擇上班打卡或下班打卡</small>
  <select id="event_type" name="event_type" required><option value="check-in">上班打卡</option><option value="check-out">下班打卡</option></select>
</div>
<button type="submit">打卡</button>
</form>
<p><a href="/login">後台登入</a></p></div>
<script>
function updateDateTime() {{
  const now = new Date();
  document.getElementById("current-date").textContent = now.toLocaleDateString("zh-TW", {{ year:"numeric", month:"long", day:"numeric", weekday:"long" }});
  document.getElementById("current-time").textContent = now.toLocaleTimeString("zh-TW", {{ hour12:false }});
}}
updateDateTime(); setInterval(updateDateTime, 1000);
</script></body></html>"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _render_kiosk_success(self, employee_name: str, event_type: str) -> None:
        type_text = "上班打卡" if event_type == "check-in" else "下班打卡"
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html_content = f"""<!doctype html>
<html lang=\"zh-Hant\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>打卡成功</title>
<style>
body {{ font-family: Arial, sans-serif; background:#eef7ee; }}
.card {{ max-width: 640px; margin: 40px auto; background:#fff; padding:24px; border-radius:14px; text-align:center; box-shadow:0 4px 14px rgba(0,0,0,.08); }}
.name {{ font-size:42px; font-weight:800; margin:8px 0; color:#0f5132; }}
.msg {{ font-size:28px; font-weight:700; margin:8px 0; }}
.time {{ font-size:20px; color:#444; }}
a {{ display:inline-block; margin-top:14px; text-decoration:none; background:#1f6feb; color:#fff; padding:10px 16px; border-radius:8px; }}
</style></head>
<body><div class=\"card\">
<h1>✅ 打卡成功</h1>
<div class=\"name\">{html.escape(employee_name)}</div>
<div class=\"msg\">{type_text}</div>
<div class=\"time\">時間：{now_text}</div>
<a href=\"/kiosk\">回到打卡頁面</a>
</div></body></html>"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _handle_login(self, form_data: dict[str, list[str]]) -> None:
        role = form_data.get("role", [""])[0].strip()
        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip() or employee_id
        password = form_data.get("password", [""])[0].strip()

        if role not in {"employee", "admin"} or not employee_id:
            self._redirect(f"/login?msg={urllib.parse.quote('登入資料不完整')}")
            return

        if role == "admin":
            if employee_id != ADMIN_ID or hash_password(password) != ADMIN_PASSWORD_HASH:
                self._redirect(f"/login?msg={urllib.parse.quote('管理員帳密錯誤')}")
                return
            employee_name = "系統管理員"
        else:
            user = get_user_by_employee_id(employee_id)
            if user and user["password_hash"] and hash_password(password) != user["password_hash"]:
                self._redirect(f"/login?msg={urllib.parse.quote('員工密碼錯誤')}")
                return
            if user:
                employee_name = user["employee_name"]

        token = create_session(role, employee_id, employee_name)
        self._redirect("/", session_token=token)

    def _handle_kiosk_clock(self, form_data: dict[str, list[str]]) -> None:
        employee_id = form_data.get("employee_id", [""])[0].strip()
        raw_password = form_data.get("password", [""])[0].strip()
        event_type = form_data.get("event_type", [""])[0].strip()

        if event_type not in {"check-in", "check-out"}:
            self._redirect(f"/kiosk?msg={urllib.parse.quote('打卡類型錯誤')}")
            return

        user = verify_employee_credentials(employee_id, raw_password)
        if not user:
            self._redirect(f"/kiosk?msg={urllib.parse.quote('員工編號或密碼錯誤')}")
            return

        latest_event = get_latest_event_type(employee_id)
        if latest_event == event_type:
            self._redirect(f"/kiosk?msg={urllib.parse.quote('打卡失敗：不可連續重複同類型打卡')}")
            return

        insert_record(employee_id, user["employee_name"], event_type)
        self._render_kiosk_success(user["employee_name"], event_type)

    def _handle_clock(self, form_data: dict[str, list[str]], session: dict[str, str]) -> None:
        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip()
        event_type = form_data.get("event_type", [""])[0].strip()

        if session["role"] != "admin":
            employee_id = session["employee_id"]
            employee_name = session["employee_name"]

        if not employee_id or not employee_name or event_type not in {"check-in", "check-out"}:
            self._redirect_with_msg("資料不完整或事件類型錯誤")
            return

        latest_event = get_latest_event_type(employee_id)
        if latest_event == event_type:
            self._redirect_with_msg("打卡失敗：不可連續重複上班或下班打卡")
            return

        insert_record(employee_id, employee_name, event_type)
        self._redirect_with_msg("打卡成功")

    def _handle_admin_employee_create(self, form_data: dict[str, list[str]], session: dict[str, str]) -> None:
        if session["role"] != "admin":
            self.send_error(HTTPStatus.FORBIDDEN, "Admin only")
            return

        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip()
        raw_password = form_data.get("password", [""])[0].strip()
        if not employee_id or not employee_name or not raw_password:
            self._redirect("/admin/employees?msg=" + urllib.parse.quote("員工資料不完整"))
            return

        insert_or_update_employee(employee_id, employee_name, raw_password)
        self._redirect("/admin/employees?msg=" + urllib.parse.quote("員工名單已更新"))

    def _handle_admin_user_update(self, form_data: dict[str, list[str]], session: dict[str, str]) -> None:
        if session["role"] != "admin":
            self.send_error(HTTPStatus.FORBIDDEN, "Admin only")
            return

        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip()
        role = form_data.get("role", [""])[0].strip()
        if not employee_id or not employee_name or role not in {"employee", "admin"}:
            self._redirect_with_msg("使用者資料不完整")
            return

        update_user(employee_id, employee_name, role)
        self._redirect_with_msg("使用者資料已更新")

    def _handle_admin_attendance_update(self, form_data: dict[str, list[str]], session: dict[str, str]) -> None:
        if session["role"] != "admin":
            self.send_error(HTTPStatus.FORBIDDEN, "Admin only")
            return

        record_id = int(form_data.get("record_id", ["0"])[0])
        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip()
        event_type = form_data.get("event_type", [""])[0].strip()
        created_at = form_data.get("created_at", [""])[0].strip()

        if not all([record_id, employee_id, employee_name, created_at]) or event_type not in {"check-in", "check-out"}:
            self._redirect_with_msg("打卡紀錄修改資料不完整")
            return

        result = update_attendance_record(record_id, employee_id, employee_name, event_type, created_at)
        if not result:
            self._redirect_with_msg("找不到要修改的紀錄")
            return

        old_data, new_data = result
        insert_audit_log(session["employee_id"], "update_attendance", record_id, old_data, new_data)
        self._redirect_with_msg("打卡紀錄已更新，並寫入稽核紀錄")

    def _render_employee_directory(self, query_string: str, session: dict[str, str]) -> None:
        if session["role"] != "admin":
            self.send_error(HTTPStatus.FORBIDDEN, "Admin only")
            return

        query = urllib.parse.parse_qs(query_string)
        message = html.escape(query.get("msg", [""])[0].strip())
        employees = fetch_employee_list()
        rows = "\n".join(
            f"<tr><td>{html.escape(row['employee_id'])}</td><td>{html.escape(row['employee_name'])}</td></tr>"
            for row in employees
        ) or '<tr><td colspan="2">尚未建立員工</td></tr>'

        html_content = f"""<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>建立員工名單</title>
<style>
body {{ font-family: Arial, sans-serif; background:#f3f6fb; }}
.container {{ max-width:900px; margin:30px auto; background:#fff; padding:20px; border-radius:12px; box-shadow:0 4px 14px rgba(0,0,0,.08); }}
input, button {{ width:100%; margin:6px 0; padding:10px; border-radius:8px; border:1px solid #c7d2e2; }}
button {{ background:#1f6feb; color:#fff; border:none; }}
.grid3 {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; align-items:end; }}
.field label {{ display:block; font-weight:700; margin-top:4px; }}
.field small {{ display:block; color:#5b6470; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
th, td {{ border-bottom:1px solid #e8edf5; padding:8px; text-align:left; }}
.hint {{ background:#eef6ff; padding:10px; border-radius:8px; margin-bottom:8px; }}
</style></head>
<body><div class=\"container\"><h1>建立員工名單</h1>
<p><a href=\"/\">回後台首頁</a> ｜ <a href=\"/kiosk\">員工打卡頁</a></p>
{f'<div class="hint">{message}</div>' if message else ''}
<form method="post" action="/admin/employee/create" class="grid3">
<div class="field">
  <label for="employee_id">員工編號（必填）</label>
  <small>請輸入唯一代碼，例如：001 或 E102</small>
  <input id="employee_id" name="employee_id" placeholder="例如：001" required>
</div>
<div class="field">
  <label for="employee_name">員工姓名（必填）</label>
  <small>請輸入員工真實姓名或顯示名稱</small>
  <input id="employee_name" name="employee_name" placeholder="例如：王小明" required>
</div>
<div class="field">
  <label for="password">打卡密碼（必填）</label>
  <small>員工在打卡頁（/kiosk）要輸入這組密碼</small>
  <input id="password" type="password" name="password" placeholder="請設定打卡密碼" required>
</div>
<button type="submit">新增 / 更新員工</button>
</form>
<table><thead><tr><th>員工編號</th><th>員工姓名</th></tr></thead><tbody>{rows}</tbody></table>
</div></body></html>"""

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _render_index(self, query_string: str, session: dict[str, str]) -> None:
        query = urllib.parse.parse_qs(query_string)
        employee_id_filter = query.get("employee_id", [""])[0].strip()
        date_filter = query.get("date", [""])[0].strip()
        message = html.escape(query.get("msg", [""])[0].strip())

        if session["role"] == "employee":
            employee_id_filter = session["employee_id"]

        rows = fetch_latest(employee_id=employee_id_filter, date=date_filter)
        users = fetch_users() if session["role"] == "admin" else []
        logs = fetch_audit_logs() if session["role"] == "admin" else []

        records_html = "\n".join(
            f"<tr><td>{r['id']}</td><td>{html.escape(r['employee_id'])}</td><td>{html.escape(r['employee_name'])}</td>"
            f"<td>{'上班' if r['event_type'] == 'check-in' else '下班'}</td><td>{html.escape(r['created_at'])}</td></tr>"
            for r in rows
        ) or '<tr><td colspan="5">目前沒有符合條件的打卡紀錄。</td></tr>'

        users_html = "\n".join(
            f"<tr><td>{html.escape(u['employee_id'])}</td><td>{html.escape(u['employee_name'])}</td><td>{html.escape(u['role'])}</td></tr>"
            for u in users
        )

        logs_html = "\n".join(
            f"<tr><td>{html.escape(l['created_at'])}</td><td>{html.escape(l['admin_employee_id'])}</td><td>{l['target_record_id']}</td>"
            f"<td>{html.escape(l['old_value'])}</td><td>{html.escape(l['new_value'])}</td></tr>"
            for l in logs
        )

        admin_sections = ""
        if session["role"] == "admin":
            admin_sections = f"""
            <h2>管理員：建立員工名單</h2>
            <p><a class=\"btn\" href=\"/admin/employees\">前往員工名單管理頁</a></p>

            <h2>管理員：編輯使用者資訊</h2>
            <form method=\"post\" action=\"/admin/user/update\" class=\"grid4\">
              <input name=\"employee_id\" placeholder=\"員工編號\" required />
              <input name=\"employee_name\" placeholder=\"員工姓名\" required />
              <select name=\"role\"><option value=\"employee\">employee</option><option value=\"admin\">admin</option></select>
              <button type=\"submit\">更新使用者</button>
            </form>
            <table><thead><tr><th>員工編號</th><th>姓名</th><th>角色</th></tr></thead><tbody>{users_html}</tbody></table>

            <h2>管理員：修改打卡紀錄（會寫入稽核）</h2>
            <form method=\"post\" action=\"/admin/attendance/update\" class=\"grid5\">
              <input name=\"record_id\" placeholder=\"紀錄ID\" required />
              <input name=\"employee_id\" placeholder=\"員工編號\" required />
              <input name=\"employee_name\" placeholder=\"員工姓名\" required />
              <select name=\"event_type\"><option value=\"check-in\">check-in</option><option value=\"check-out\">check-out</option></select>
              <input name=\"created_at\" placeholder=\"YYYY-MM-DD HH:MM:SS\" required />
              <button type=\"submit\">更新打卡紀錄</button>
            </form>

            <h2>管理員：下載 Excel</h2>
            <a class=\"btn\" href=\"/export.xls?employee_id={urllib.parse.quote(employee_id_filter)}&date={urllib.parse.quote(date_filter)}\">下載 Excel（.xls）</a>

            <h2>稽核紀錄（管理員每次修改打卡都會記錄）</h2>
            <table><thead><tr><th>時間</th><th>管理員</th><th>紀錄ID</th><th>舊值</th><th>新值</th></tr></thead><tbody>{logs_html}</tbody></table>
            """

        employee_clock_fields = ""
        if session["role"] == "admin":
            employee_clock_fields = """
            <input type=\"text\" name=\"employee_id\" placeholder=\"員工編號\" required />
            <input type=\"text\" name=\"employee_name\" placeholder=\"員工姓名\" required />
            """

        html_content = f"""<!doctype html>
<html lang=\"zh-Hant\"><head><meta charset=\"UTF-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
<title>員工線上打卡系統</title>
<style>
body {{ font-family: Arial, sans-serif; background: #f3f6fb; margin: 0; }}
.container {{ max-width: 1100px; margin: 24px auto; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 14px rgba(0,0,0,.08); }}
input, select, button {{ padding: 10px; border-radius: 8px; border: 1px solid #c7d2e2; font-size: 14px; }}
button, .btn {{ background: #1f6feb; color: white; border: none; text-decoration:none; display:inline-block; padding:10px 14px; border-radius:8px; }}
.grid3 {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; margin-bottom:12px; }}
.grid4 {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:12px; }}
.grid5 {{ display:grid; grid-template-columns: repeat(6, 1fr); gap:10px; margin-bottom:12px; }}
.hint {{ background: #eef6ff; color: #154b8b; border: 1px solid #d4e6ff; padding: 10px; border-radius: 8px; margin-bottom: 16px; }}
.datetime-board {{ background: linear-gradient(135deg, #0f4c81, #1f6feb); color: #fff; border-radius: 14px; padding: 16px 20px; margin-bottom: 18px; text-align: center; }}
.datetime-date {{ font-size: 34px; font-weight: 700; }}
.datetime-time {{ font-size: 62px; font-weight: 800; line-height: 1.1; margin-top: 6px; font-variant-numeric: tabular-nums; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; margin-bottom:20px; }}
th, td {{ border-bottom:1px solid #e8edf5; padding:8px; text-align:left; font-size:13px; }}
</style></head>
<body><div class=\"container\">
<h1>員工線上打卡系統（{html.escape(session['role'])}）</h1>
<p>登入者：{html.escape(session['employee_id'])} / {html.escape(session['employee_name'])} ｜ <a href=\"/logout\">登出</a> ｜ <a href=\"/kiosk\">員工打卡頁</a></p>
<div class=\"datetime-board\"><div class=\"datetime-date\" id=\"current-date\">--</div><div class=\"datetime-time\" id=\"current-time\">--:--:--</div></div>
{f'<div class="hint">{message}</div>' if message else ''}
<h2>打卡</h2>
<form method=\"post\" action=\"/clock\" class=\"grid4\">{employee_clock_fields}<select name=\"event_type\" required><option value=\"check-in\">上班打卡</option><option value=\"check-out\">下班打卡</option></select><button type=\"submit\">送出</button></form>
<h2>查詢紀錄</h2>
<form method=\"get\" action=\"/\" class=\"grid3\"><input type=\"text\" name=\"employee_id\" value=\"{html.escape(employee_id_filter)}\" placeholder=\"員工編號\" /><input type=\"date\" name=\"date\" value=\"{html.escape(date_filter)}\" /><button type=\"submit\">查詢</button></form>
<table><thead><tr><th>ID</th><th>員工編號</th><th>員工姓名</th><th>類型</th><th>時間</th></tr></thead><tbody>{records_html}</tbody></table>
{admin_sections}
</div>
<script>
function updateDateTime() {{
  const now = new Date();
  document.getElementById("current-date").textContent = now.toLocaleDateString("zh-TW", {{ year:"numeric", month:"long", day:"numeric", weekday:"long" }});
  document.getElementById("current-time").textContent = now.toLocaleTimeString("zh-TW", {{ hour12:false }});
}}
updateDateTime(); setInterval(updateDateTime, 1000);
</script></body></html>"""

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _render_records_json(self, query_string: str, session: dict[str, str]) -> None:
        query = urllib.parse.parse_qs(query_string)
        employee_id = query.get("employee_id", [""])[0].strip()
        date = query.get("date", [""])[0].strip()
        if session["role"] != "admin":
            employee_id = session["employee_id"]
        records = fetch_all(employee_id=employee_id, date=date)
        payload = json.dumps([dict(row) for row in records], ensure_ascii=False)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def _render_records_excel(self, query_string: str, session: dict[str, str]) -> None:
        if session["role"] != "admin":
            self.send_error(HTTPStatus.FORBIDDEN, "Admin only")
            return

        query = urllib.parse.parse_qs(query_string)
        employee_id = query.get("employee_id", [""])[0].strip()
        date = query.get("date", [""])[0].strip()
        records = fetch_all(employee_id=employee_id, date=date)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "employee_id", "employee_name", "event_type", "created_at"])
        for row in records:
            writer.writerow([row["id"], row["employee_id"], row["employee_name"], row["event_type"], row["created_at"]])

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.ms-excel; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="attendance_records.xls"')
        self.end_headers()
        self.wfile.write(output.getvalue().encode("utf-8-sig"))


def _find_available_port(start_port: int, max_tries: int = 20) -> int:
    for candidate in range(start_port, start_port + max_tries):
        try:
            test_server = ThreadingHTTPServer((HOST, candidate), AttendanceHandler)
            test_server.server_close()
            return candidate
        except OSError:
            continue
    raise OSError("No available port found")


def run() -> None:
    init_db()
    port = _find_available_port(PORT)
    server = ThreadingHTTPServer((HOST, port), AttendanceHandler)
    if port != PORT:
        print(f"Port {PORT} 已被占用，改用 http://127.0.0.1:{port}")
    else:
        print(f"Server running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
