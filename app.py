from __future__ import annotations

import sqlite3
import urllib.parse
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"
HOST = "0.0.0.0"
PORT = 5000


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
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


def fetch_latest(limit: int = 50) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT employee_id, employee_name, event_type, created_at
            FROM attendance
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def fetch_all() -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT employee_id, employee_name, event_type, created_at
            FROM attendance
            ORDER BY id DESC
            """
        ).fetchall()


def insert_record(employee_id: str, employee_name: str, event_type: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO attendance (employee_id, employee_name, event_type, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (employee_id, employee_name, event_type, timestamp),
        )


class AttendanceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self._render_index()
            return

        if self.path == "/api/records":
            self._render_records_json()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        if self.path != "/clock":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        form_data = urllib.parse.parse_qs(body)

        employee_id = form_data.get("employee_id", [""])[0].strip()
        employee_name = form_data.get("employee_name", [""])[0].strip()
        event_type = form_data.get("event_type", [""])[0].strip()

        if not employee_id or not employee_name or event_type not in {"check-in", "check-out"}:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("資料不完整或事件類型錯誤".encode("utf-8"))
            return

        insert_record(employee_id, employee_name, event_type)

        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def _render_index(self) -> None:
        rows = fetch_latest()
        html_rows = "\n".join(
            f"<tr><td>{r['employee_id']}</td><td>{r['employee_name']}</td>"
            f"<td>{'上班' if r['event_type'] == 'check-in' else '下班'}</td><td>{r['created_at']}</td></tr>"
            for r in rows
        )
        if not html_rows:
            html_rows = '<tr><td colspan="4">目前沒有打卡紀錄。</td></tr>'

        html = f"""<!doctype html>
<html lang=\"zh-Hant\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>員工線上打卡系統</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f3f6fb; margin: 0; }}
    .container {{ max-width: 900px; margin: 24px auto; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 14px rgba(0,0,0,.08); }}
    h1 {{ margin-top: 0; }}
    form {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
    input, select, button {{ padding: 10px; border-radius: 8px; border: 1px solid #c7d2e2; font-size: 14px; }}
    button {{ background: #1f6feb; color: white; border: none; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e8edf5; padding: 10px; text-align: left; }}
    th {{ background: #f8fbff; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <h1>員工線上打卡系統</h1>
    <form method=\"post\" action=\"/clock\">
      <input type=\"text\" name=\"employee_id\" placeholder=\"員工編號（例如 E001）\" required />
      <input type=\"text\" name=\"employee_name\" placeholder=\"員工姓名\" required />
      <select name=\"event_type\" required>
        <option value=\"check-in\">上班打卡</option>
        <option value=\"check-out\">下班打卡</option>
      </select>
      <button type=\"submit\">送出</button>
    </form>

    <table>
      <thead>
        <tr><th>員工編號</th><th>員工姓名</th><th>類型</th><th>時間</th></tr>
      </thead>
      <tbody>{html_rows}</tbody>
    </table>
  </div>
</body>
</html>
"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _render_records_json(self) -> None:
        records = fetch_all()
        json_rows = [
            "{" + ", ".join(
                [
                    f'\"employee_id\": \"{r["employee_id"]}\"',
                    f'\"employee_name\": \"{r["employee_name"]}\"',
                    f'\"event_type\": \"{r["event_type"]}\"',
                    f'\"created_at\": \"{r["created_at"]}\"',
                ]
            ) + "}"
            for r in records
        ]
        payload = "[" + ", ".join(json_rows) + "]"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))


def run() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AttendanceHandler)
    print(f"Server running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
