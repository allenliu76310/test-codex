from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pos.db"

app = Flask(__name__)


WAITER_TEMPLATE = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>雲端餐飲 POS - 點餐台</title>
  <style>
    :root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f3f5f9; color: #111827; }
    header { padding: 14px 16px; background: #1f2937; color: white; display: flex; justify-content: space-between; align-items: center; }
    .container { display: grid; grid-template-columns: 1fr; gap: 14px; padding: 14px; }
    .card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,.08); padding: 14px; }
    .menu-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .menu-item { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; }
    .menu-item h4 { margin: 0 0 8px; font-size: 16px; }
    .menu-item .price { color: #2563eb; font-weight: 700; margin-bottom: 8px; }
    button { border: 0; background: #2563eb; color: white; padding: 8px 10px; border-radius: 8px; font-weight: 600; }
    button.secondary { background: #6b7280; }
    .cart-row { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-bottom: 1px dashed #e5e7eb; }
    .row { display: flex; gap: 8px; margin-top: 10px; }
    input, textarea, select { width: 100%; border: 1px solid #d1d5db; border-radius: 8px; padding: 8px; font-size: 15px; }
    .muted { color: #6b7280; font-size: 13px; }
    @media (min-width: 960px) {
      .container { grid-template-columns: 2fr 1fr; }
      .menu-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <strong>🍽️ 雲端餐飲 POS / 服務人員點餐</strong>
    <a href="{{ url_for('dashboard') }}" style="color:#93c5fd">銷售後台</a>
  </header>

  <main class="container">
    <section class="card">
      <h3 style="margin-top:0;">菜單</h3>
      <div id="menu" class="menu-grid"></div>
    </section>

    <aside class="card">
      <h3 style="margin-top:0;">訂單</h3>
      <div class="row">
        <input id="tableNo" placeholder="桌號，例如 A12" />
      </div>
      <div class="row">
        <select id="staffName">
          <option value="Amy">Amy</option>
          <option value="Bob">Bob</option>
          <option value="Cindy">Cindy</option>
        </select>
      </div>
      <div id="cart"></div>
      <p class="muted">小計：NT$ <span id="subtotal">0</span></p>
      <div class="row">
        <textarea id="note" rows="2" placeholder="備註：少冰、不辣..."></textarea>
      </div>
      <div class="row">
        <button onclick="submitOrder()">送出訂單</button>
        <button class="secondary" onclick="clearCart()">清空</button>
      </div>
      <p id="message" class="muted"></p>
    </aside>
  </main>

<script>
  let menu = [];
  const cart = new Map();

  function renderMenu() {
    const el = document.getElementById('menu');
    el.innerHTML = menu.map(item => `
      <div class="menu-item">
        <h4>${item.name}</h4>
        <div class="muted">${item.category}</div>
        <div class="price">NT$ ${item.price}</div>
        <button onclick="addItem(${item.id})">加入</button>
      </div>
    `).join('');
  }

  function addItem(itemId) {
    const qty = cart.get(itemId) || 0;
    cart.set(itemId, qty + 1);
    renderCart();
  }

  function removeItem(itemId) {
    const qty = cart.get(itemId) || 0;
    if (qty <= 1) cart.delete(itemId);
    else cart.set(itemId, qty - 1);
    renderCart();
  }

  function clearCart() {
    cart.clear();
    renderCart();
  }

  function renderCart() {
    const cartEl = document.getElementById('cart');
    let total = 0;
    const rows = [];
    for (const [id, qty] of cart.entries()) {
      const item = menu.find(m => m.id === id);
      if (!item) continue;
      total += item.price * qty;
      rows.push(`<div class="cart-row"><span>${item.name} x ${qty}</span><span><button class="secondary" onclick="removeItem(${id})">-</button></span></div>`)
    }
    cartEl.innerHTML = rows.join('') || '<p class="muted">尚未加入品項</p>';
    document.getElementById('subtotal').textContent = total;
  }

  async function loadMenu() {
    const res = await fetch('/api/menu');
    menu = await res.json();
    renderMenu();
    renderCart();
  }

  async function submitOrder() {
    const table_no = document.getElementById('tableNo').value.trim();
    const staff_name = document.getElementById('staffName').value;
    const note = document.getElementById('note').value;
    if (!table_no) return alert('請輸入桌號');
    if (!cart.size) return alert('請先加入至少一個品項');

    const items = Array.from(cart.entries()).map(([menu_item_id, quantity]) => ({ menu_item_id, quantity }));
    const res = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table_no, staff_name, note, items })
    });
    const data = await res.json();
    document.getElementById('message').textContent = data.message || '送出完成';
    if (res.ok) {
      clearCart();
      document.getElementById('note').value = '';
      document.getElementById('tableNo').value = '';
    }
  }

  loadMenu();
</script>
</body>
</html>
"""


DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>雲端餐飲 POS - 即時銷售後台</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f9fafb; color:#111827; }
    header { background:#111827; color:white; padding:14px 16px; display:flex; justify-content:space-between; }
    .wrapper { padding:14px; display:grid; gap:14px; }
    .cards { display:grid; gap:10px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
    .card { background:white; border-radius:12px; padding:12px; box-shadow:0 2px 10px rgba(0,0,0,.08); }
    .metric { font-size:28px; font-weight:700; margin:4px 0; }
    canvas { width:100% !important; max-height:360px; }
  </style>
</head>
<body>
  <header>
    <strong>📈 即時銷售數據後台</strong>
    <a href="{{ url_for('waiter') }}" style="color:#93c5fd">回點餐台</a>
  </header>

  <main class="wrapper">
    <section class="cards">
      <div class="card"><div>今日營收</div><div id="todayRevenue" class="metric">0</div></div>
      <div class="card"><div>今日訂單數</div><div id="todayOrders" class="metric">0</div></div>
      <div class="card"><div>平均客單價</div><div id="avgOrder" class="metric">0</div></div>
      <div class="card"><div>近一小時營收</div><div id="lastHour" class="metric">0</div></div>
    </section>

    <section class="card"><h3>每小時營收</h3><canvas id="hourlyChart"></canvas></section>
    <section class="card"><h3>熱銷品項 Top 5</h3><canvas id="topItemsChart"></canvas></section>
  </main>

<script>
  const hourlyChart = new Chart(document.getElementById('hourlyChart'), {
    type: 'line',
    data: { labels: [], datasets: [{ label: '營收', data: [], tension: 0.25 }] },
    options: { responsive: true, maintainAspectRatio: false }
  });

  const topItemsChart = new Chart(document.getElementById('topItemsChart'), {
    type: 'bar',
    data: { labels: [], datasets: [{ label: '銷售數量', data: [] }] },
    options: { responsive: true, maintainAspectRatio: false }
  });

  function fmt(v) { return 'NT$ ' + Number(v).toLocaleString('zh-TW'); }

  async function refreshData() {
    const res = await fetch('/api/sales/realtime');
    const data = await res.json();

    document.getElementById('todayRevenue').textContent = fmt(data.metrics.today_revenue);
    document.getElementById('todayOrders').textContent = data.metrics.today_orders;
    document.getElementById('avgOrder').textContent = fmt(data.metrics.avg_order_value);
    document.getElementById('lastHour').textContent = fmt(data.metrics.last_hour_revenue);

    hourlyChart.data.labels = data.hourly_sales.map(x => x.hour);
    hourlyChart.data.datasets[0].data = data.hourly_sales.map(x => x.revenue);
    hourlyChart.update();

    topItemsChart.data.labels = data.top_items.map(x => x.name);
    topItemsChart.data.datasets[0].data = data.top_items.map(x => x.quantity);
    topItemsChart.update();
  }

  refreshData();
  setInterval(refreshData, 5000);
</script>
</body>
</html>
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_no TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'submitted',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(menu_item_id) REFERENCES menu_items(id)
        );
        """
    )

    cur.execute("SELECT COUNT(*) AS count FROM menu_items")
    if cur.fetchone()["count"] == 0:
        cur.executemany(
            "INSERT INTO menu_items (name, category, price) VALUES (?, ?, ?)",
            [
                ("招牌牛肉麵", "主食", 220),
                ("滷肉飯", "主食", 95),
                ("凱薩沙拉", "前菜", 160),
                ("鹽酥雞", "小食", 180),
                ("珍珠奶茶", "飲料", 75),
                ("冬瓜檸檬", "飲料", 65),
                ("提拉米蘇", "甜點", 130),
                ("炸薯條", "小食", 90),
            ],
        )

    cur.execute("SELECT COUNT(*) AS count FROM orders")
    if cur.fetchone()["count"] == 0:
        seed_demo_orders(conn)

    conn.commit()
    conn.close()


def seed_demo_orders(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT id, price FROM menu_items")
    price_map = {row["id"]: row["price"] for row in cur.fetchall()}

    now = datetime.utcnow()
    demo = [
        ("A1", "Amy", [(1, 1), (5, 2)], 5),
        ("B3", "Bob", [(2, 2), (8, 1), (6, 1)], 60),
        ("C2", "Cindy", [(1, 1), (3, 1), (7, 1)], 110),
        ("A4", "Amy", [(4, 1), (5, 3)], 170),
    ]

    for table_no, staff, items, minutes_ago in demo:
        created_at = (now - timedelta(minutes=minutes_ago)).isoformat()
        cur.execute(
            "INSERT INTO orders (table_no, staff_name, note, created_at) VALUES (?, ?, ?, ?)",
            (table_no, staff, "demo", created_at),
        )
        order_id = cur.lastrowid
        for menu_id, qty in items:
            cur.execute(
                "INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                (order_id, menu_id, qty, price_map[menu_id]),
            )


@app.get("/")
def index() -> Any:
    return redirect(url_for("waiter"))


@app.get("/waiter")
def waiter() -> str:
    return render_template_string(WAITER_TEMPLATE)


@app.get("/dashboard")
def dashboard() -> str:
    return render_template_string(DASHBOARD_TEMPLATE)


@app.get("/api/menu")
def list_menu() -> Any:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, category, price FROM menu_items WHERE is_active = 1 ORDER BY category, id"
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.post("/api/orders")
def create_order() -> Any:
    payload = request.get_json(silent=True) or {}
    table_no = str(payload.get("table_no", "")).strip()
    staff_name = str(payload.get("staff_name", "")).strip() or "Unknown"
    note = str(payload.get("note", "")).strip()
    items = payload.get("items", [])

    if not table_no:
        return jsonify({"message": "桌號不可為空"}), 400
    if not items:
        return jsonify({"message": "至少需一個品項"}), 400

    conn = get_conn()
    cur = conn.cursor()

    menu_ids = [int(item.get("menu_item_id", 0)) for item in items]
    placeholders = ",".join(["?"] * len(menu_ids))
    menu_rows = cur.execute(
        f"SELECT id, price FROM menu_items WHERE id IN ({placeholders})",  # noqa: S608
        menu_ids,
    ).fetchall()
    menu_map = {row["id"]: row["price"] for row in menu_rows}

    if len(menu_map) != len(set(menu_ids)):
        conn.close()
        return jsonify({"message": "品項資料有誤"}), 400

    created_at = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO orders (table_no, staff_name, note, created_at) VALUES (?, ?, ?, ?)",
        (table_no, staff_name, note, created_at),
    )
    order_id = cur.lastrowid

    for item in items:
        menu_id = int(item["menu_item_id"])
        qty = max(1, int(item.get("quantity", 1)))
        cur.execute(
            "INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, menu_id, qty, menu_map[menu_id]),
        )

    conn.commit()
    conn.close()
    return jsonify({"message": f"訂單 #{order_id} 已送出"})


@app.get("/api/sales/realtime")
def realtime_sales() -> Any:
    conn = get_conn()
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    hour_ago = (now - timedelta(hours=1)).isoformat()

    today_orders = conn.execute(
        "SELECT id, created_at FROM orders WHERE created_at >= ?",
        (day_start,),
    ).fetchall()

    today_order_ids = [row["id"] for row in today_orders]
    today_count = len(today_order_ids)

    today_revenue = 0
    last_hour_revenue = 0
    hourly = defaultdict(int)

    if today_order_ids:
        placeholders = ",".join(["?"] * len(today_order_ids))
        items = conn.execute(
            f"""
            SELECT oi.quantity, oi.unit_price, o.created_at
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.order_id IN ({placeholders})
            """,  # noqa: S608
            today_order_ids,
        ).fetchall()

        for row in items:
            revenue = row["quantity"] * row["unit_price"]
            created = datetime.fromisoformat(row["created_at"])
            today_revenue += revenue
            hourly[created.strftime("%H:00")] += revenue
            if row["created_at"] >= hour_ago:
                last_hour_revenue += revenue

    hourly_sales = []
    for h in range(24):
        label = f"{h:02d}:00"
        hourly_sales.append({"hour": label, "revenue": hourly[label]})

    top_items_rows = conn.execute(
        """
        SELECT m.name, SUM(oi.quantity) AS total_qty
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN menu_items m ON m.id = oi.menu_item_id
        WHERE o.created_at >= ?
        GROUP BY m.name
        ORDER BY total_qty DESC
        LIMIT 5
        """,
        (day_start,),
    ).fetchall()
    conn.close()

    avg_order = round(today_revenue / today_count, 2) if today_count else 0

    return jsonify(
        {
            "metrics": {
                "today_revenue": today_revenue,
                "today_orders": today_count,
                "avg_order_value": avg_order,
                "last_hour_revenue": last_hour_revenue,
            },
            "hourly_sales": hourly_sales,
            "top_items": [
                {"name": row["name"], "quantity": row["total_qty"]} for row in top_items_rows
            ],
            "generated_at": now.isoformat(),
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
