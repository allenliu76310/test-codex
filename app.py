from __future__ import annotations

import cgi
import csv
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

cv2 = None
np = None

HOST = "0.0.0.0"
PORT = 5000
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


@dataclass
class PersonTrack:
    person_id: int
    embedding: object
    appearances: int = 1


@dataclass
class AnalysisTask:
    task_id: str
    filename: str
    status: str = "queued"  # queued/running/completed/failed/cancelled
    progress: int = 0
    message: str = "等待中"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict | None = None
    error: str | None = None
    cancel_requested: bool = False


TASKS: dict[str, AnalysisTask] = {}
TASK_LOCK = threading.Lock()
START_TIME = time.time()


def _log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def _wait_before_exit(message: str = "按 Enter 鍵關閉視窗...") -> None:
    if os.environ.get("NO_PAUSE_ON_EXIT") == "1":
        return

    try:
        input(message)
    except EOFError:
        # 某些視窗執行模式沒有可互動 stdin，改用短暫停留避免瞬間關閉
        _log("無法讀取鍵盤輸入，將在 10 秒後自動關閉...")
        time.sleep(10)


def _status_monitor(stop_event: threading.Event, interval_seconds: int = 10) -> None:
    while not stop_event.wait(interval_seconds):
        with TASK_LOCK:
            total = len(TASKS)
            running = sum(1 for t in TASKS.values() if t.status == "running")
            queued = sum(1 for t in TASKS.values() if t.status == "queued")
            done = sum(1 for t in TASKS.values() if t.status == "completed")
            failed = sum(1 for t in TASKS.values() if t.status == "failed")
            cancelled = sum(1 for t in TASKS.values() if t.status == "cancelled")
        uptime = int(time.time() - START_TIME)
        _log(
            f"服務運行中 | uptime={uptime}s | 任務 total={total}, queued={queued}, running={running}, completed={done}, failed={failed}, cancelled={cancelled}"
        )

def _load_dependencies() -> tuple[object, object]:
    global cv2, np
    if cv2 is not None and np is not None:
        return cv2, np

    cv2_spec = importlib.util.find_spec("cv2")
    np_spec = importlib.util.find_spec("numpy")
    if cv2_spec is None or np_spec is None:
        raise RuntimeError(
            "缺少必要套件：opencv-python 與 numpy。"
            "請先執行 `pip install -r requirements.txt` 後再分析影片。"
        )

    cv2 = importlib.import_module("cv2")
    np = importlib.import_module("numpy")
    return cv2, np


def _cosine_similarity(a: object, b: object, np_module: object) -> float:
    denominator = (np_module.linalg.norm(a) * np_module.linalg.norm(b))
    if denominator == 0:
        return 0.0
    return float(np_module.dot(a, b) / denominator)


def _face_embedding(face_gray: object, cv2_module: object, np_module: object) -> object:
    normalized = cv2_module.resize(face_gray, (64, 64), interpolation=cv2_module.INTER_AREA)
    embedding = normalized.astype(np_module.float32).flatten()
    mean = embedding.mean()
    std = embedding.std()
    if std < 1e-6:
        return embedding - mean
    return (embedding - mean) / std


def analyze_video(
    video_path: Path,
    frame_stride: int = 12,
    similarity_threshold: float = 0.86,
    progress_callback: callable | None = None,
    should_cancel: callable | None = None,
) -> dict:
    cv2_module, np_module = _load_dependencies()

    cascade_path = cv2_module.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2_module.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError("無法載入人臉偵測模型（Haar Cascade）。")

    cap = cv2_module.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("影片無法開啟，請確認檔案格式。")

    fps = cap.get(cv2_module.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    total_frames = int(cap.get(cv2_module.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        total_frames = 1

    tracks: list[PersonTrack] = []
    frame_index = 0
    total_faces_detected = 0
    sampled_frames = 0

    try:
        while True:
            if should_cancel and should_cancel():
                raise RuntimeError("使用者已取消分析")

            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % frame_stride != 0:
                frame_index += 1
                if progress_callback:
                    progress_callback(min(95, int((frame_index / total_frames) * 100)), "分析中")
                continue

            sampled_frames += 1
            gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40),
            )

            for x, y, w, h in faces:
                roi = gray[y : y + h, x : x + w]
                embedding = _face_embedding(roi, cv2_module, np_module)
                total_faces_detected += 1

                if not tracks:
                    tracks.append(PersonTrack(person_id=1, embedding=embedding))
                    continue

                similarities = [_cosine_similarity(embedding, t.embedding, np_module) for t in tracks]
                best_idx = int(np_module.argmax(similarities))
                best_score = similarities[best_idx]

                if best_score >= similarity_threshold:
                    track = tracks[best_idx]
                    track.appearances += 1
                    track.embedding = (0.85 * track.embedding) + (0.15 * embedding)
                else:
                    tracks.append(PersonTrack(person_id=len(tracks) + 1, embedding=embedding))

            frame_index += 1
            if progress_callback:
                progress_callback(min(95, int((frame_index / total_frames) * 100)), "分析中")
    finally:
        cap.release()

    duration_seconds = frame_index / fps if fps else 0.0
    people = [
        {
            "person_id": t.person_id,
            "appearances": t.appearances,
            "is_repeated": t.appearances > 1,
        }
        for t in tracks
    ]

    repeated_count = sum(1 for t in tracks if t.appearances > 1)
    if progress_callback:
        progress_callback(100, "分析完成")

    return {
        "video": video_path.name,
        "duration_seconds": round(duration_seconds, 2),
        "sampled_frames": sampled_frames,
        "faces_detected": total_faces_detected,
        "unique_people": len(tracks),
        "repeated_people": repeated_count,
        "people": people,
    }


def _task_to_dict(task: AnalysisTask) -> dict:
    return {
        "task_id": task.task_id,
        "filename": task.filename,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result": task.result,
        "error": task.error,
    }


def _update_task(task_id: str, **changes: object) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        for key, value in changes.items():
            setattr(task, key, value)
        task.updated_at = time.time()


def _process_task(task_id: str, temp_path: Path) -> None:
    _update_task(task_id, status="running", progress=1, message="初始化分析")
    _log(f"任務開始：{task_id} ({Path(temp_path).name})")

    def on_progress(value: int, message: str) -> None:
        _update_task(task_id, progress=value, message=message)

    def should_cancel() -> bool:
        with TASK_LOCK:
            task = TASKS.get(task_id)
            return bool(task and task.cancel_requested)

    try:
        result = analyze_video(temp_path, progress_callback=on_progress, should_cancel=should_cancel)
        _update_task(task_id, status="completed", progress=100, message="分析完成", result=result)
        _log(f"任務完成：{task_id}")
    except RuntimeError as exc:
        msg = str(exc)
        if "取消" in msg:
            _update_task(task_id, status="cancelled", message="已取消", error=msg)
            _log(f"任務取消：{task_id}")
        else:
            _update_task(task_id, status="failed", message="分析失敗", error=msg)
            _log(f"任務失敗：{task_id} | {msg}")
    except Exception as exc:  # noqa: BLE001
        _update_task(task_id, status="failed", message="分析失敗", error=f"{exc}")
        _log(f"任務異常：{task_id} | {exc}")
    finally:
        if temp_path.exists():
            os.remove(temp_path)


def _result_to_csv_bytes(result: dict) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["video", result.get("video", "")])
    writer.writerow(["duration_seconds", result.get("duration_seconds", 0)])
    writer.writerow(["sampled_frames", result.get("sampled_frames", 0)])
    writer.writerow(["faces_detected", result.get("faces_detected", 0)])
    writer.writerow(["unique_people", result.get("unique_people", 0)])
    writer.writerow(["repeated_people", result.get("repeated_people", 0)])
    writer.writerow([])
    writer.writerow(["person_id", "appearances", "is_repeated"])
    for person in result.get("people", []):
        writer.writerow([person["person_id"], person["appearances"], person["is_repeated"]])
    return buffer.getvalue().encode("utf-8-sig")


class FaceVideoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._render_html().encode("utf-8"))
            return

        parsed = urlparse(self.path)
        path_parts = [part for part in parsed.path.split("/") if part]

        if len(path_parts) == 3 and path_parts[0] == "api" and path_parts[1] == "task":
            self._handle_get_task(path_parts[2])
            return

        if len(path_parts) == 4 and path_parts[0] == "api" and path_parts[1] == "task" and path_parts[3] == "export":
            self._handle_export(path_parts[2], parse_qs(parsed.query))
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path_parts = [part for part in parsed.path.split("/") if part]

        if parsed.path == "/analyze":
            try:
                task = self._enqueue_analysis_task()
                self._send_json(HTTPStatus.ACCEPTED, _task_to_dict(task))
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"分析失敗：{exc}"})
            return

        if len(path_parts) == 4 and path_parts[0] == "api" and path_parts[1] == "task" and path_parts[3] == "cancel":
            self._handle_cancel(path_parts[2])
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _handle_get_task(self, task_id: str) -> None:
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if not task:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到任務"})
                return
            payload = _task_to_dict(task)
        self._send_json(HTTPStatus.OK, payload)

    def _handle_cancel(self, task_id: str) -> None:
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if not task:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到任務"})
                return
            if task.status in {"completed", "failed", "cancelled"}:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"任務狀態為 {task.status}，無法取消"})
                return
            task.cancel_requested = True
            task.message = "取消中"
            task.updated_at = time.time()
        self._send_json(HTTPStatus.OK, {"task_id": task_id, "status": "cancelling"})

    def _handle_export(self, task_id: str, query: dict[str, list[str]]) -> None:
        fmt = (query.get("format", ["json"])[0] or "json").lower()
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if not task:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "找不到任務"})
                return
            if task.status != "completed" or task.result is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "任務尚未完成，無法匯出"})
                return
            result = task.result

        if fmt == "json":
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            filename = f"analysis-{task_id}.json"
            content_type = "application/json; charset=utf-8"
        elif fmt == "csv":
            body = _result_to_csv_bytes(result)
            filename = f"analysis-{task_id}.csv"
            content_type = "text/csv; charset=utf-8"
        else:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "format 僅支援 json 或 csv"})
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _enqueue_analysis_task(self) -> AnalysisTask:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("請使用 multipart/form-data 上傳影片。")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
            },
        )

        file_item = form["video"] if "video" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            raise ValueError("請上傳影片檔案。")

        filename = Path(file_item.filename).name
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支援的副檔名：{ext}。支援格式：{', '.join(sorted(ALLOWED_EXTENSIONS))}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            temp_file.write(file_item.file.read())
            temp_path = Path(temp_file.name)

        task = AnalysisTask(task_id=uuid.uuid4().hex[:12], filename=filename)
        with TASK_LOCK:
            TASKS[task.task_id] = task

        worker = threading.Thread(target=_process_task, args=(task.task_id, temp_path), daemon=True)
        worker.start()
        _log(f"任務已建立：{task.task_id} | 檔案={filename}")
        return task

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _render_html(self) -> str:
        return """<!doctype html>
<html lang=\"zh-Hant\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>影片人臉重複辨識</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f4f7fc; color: #1e293b; }
    .container { max-width: 920px; margin: 32px auto; background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }
    .dropzone { border: 2px dashed #93c5fd; border-radius: 12px; padding: 30px; text-align: center; background: #eff6ff; cursor: pointer; }
    .dropzone.dragover { border-color: #2563eb; background: #dbeafe; }
    .meta { color: #475569; }
    .controls { margin-top: 16px; display: flex; gap: 10px; flex-wrap: wrap; }
    button { border: none; border-radius: 10px; padding: 10px 16px; font-size: 15px; cursor: pointer; }
    button:disabled { opacity: .6; cursor: not-allowed; }
    .primary { background: #2563eb; color: #fff; }
    .danger { background: #dc2626; color: #fff; }
    .secondary { background: #0f766e; color: #fff; }
    .progress-wrap { margin-top: 16px; background: #e2e8f0; border-radius: 999px; height: 14px; overflow: hidden; }
    .progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #0ea5e9); transition: width .2s ease; }
    #statusText { margin-top: 8px; color: #334155; }
    #result { margin-top: 24px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { border-bottom: 1px solid #e2e8f0; padding: 10px; text-align: left; }
    th { background: #f8fafc; }
    .error { color: #b91c1c; font-weight: 700; }
    .success { color: #166534; font-weight: 700; }
  </style>
</head>
<body>
  <div class=\"container\">
    <h1>影片人臉重複辨識工具</h1>
    <p>拖曳影片到下方區塊，系統會偵測影片中的人臉並判斷是否重複出現。</p>

    <div id=\"dropzone\" class=\"dropzone\">
      <p><strong>拖曳影片到這裡，或點擊選擇檔案</strong></p>
      <p class=\"meta\">支援：.mp4 .mov .avi .mkv .m4v</p>
      <input id=\"videoInput\" type=\"file\" accept=\"video/*\" hidden />
      <p id=\"selectedFile\" class=\"meta\">尚未選擇檔案</p>
    </div>

    <div class=\"controls\">
      <button id=\"analyzeBtn\" class=\"primary\" disabled>開始分析</button>
      <button id=\"cancelBtn\" class=\"danger\" disabled>取消分析</button>
      <button id=\"exportJsonBtn\" class=\"secondary\" disabled>匯出 JSON</button>
      <button id=\"exportCsvBtn\" class=\"secondary\" disabled>匯出 CSV</button>
    </div>

    <div class=\"progress-wrap\"><div id=\"progressBar\" class=\"progress-bar\"></div></div>
    <div id=\"statusText\">尚未開始分析</div>

    <div id=\"result\"></div>
  </div>

  <script>
    const dropzone = document.getElementById('dropzone');
    const videoInput = document.getElementById('videoInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const cancelBtn = document.getElementById('cancelBtn');
    const exportJsonBtn = document.getElementById('exportJsonBtn');
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const selectedFile = document.getElementById('selectedFile');
    const progressBar = document.getElementById('progressBar');
    const statusText = document.getElementById('statusText');
    const result = document.getElementById('result');

    let file = null;
    let currentTaskId = null;
    let pollTimer = null;

    function setFile(f) {
      file = f;
      selectedFile.textContent = f ? `已選擇：${f.name}` : '尚未選擇檔案';
      analyzeBtn.disabled = !f;
      result.innerHTML = '';
      exportJsonBtn.disabled = true;
      exportCsvBtn.disabled = true;
    }

    function setProgress(value, text) {
      progressBar.style.width = `${value}%`;
      statusText.textContent = `${text} (${value}%)`;
    }

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function renderResult(data) {
      const rows = (data.people || []).map((p) => `
        <tr>
          <td>人物 ${p.person_id}</td>
          <td>${p.appearances}</td>
          <td>${p.is_repeated ? '是' : '否'}</td>
        </tr>
      `).join('');

      result.innerHTML = `
        <p class=\"success\">分析完成：${data.video}</p>
        <ul>
          <li>影片長度：約 ${data.duration_seconds} 秒</li>
          <li>抽樣幀數：${data.sampled_frames}</li>
          <li>偵測到人臉次數：${data.faces_detected}</li>
          <li>辨識到不同人物數：${data.unique_people}</li>
          <li>重複出現人物數：${data.repeated_people}</li>
        </ul>
        <table>
          <thead><tr><th>人物</th><th>出現次數</th><th>是否重複出現</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="3">沒有偵測到人臉</td></tr>'}</tbody>
        </table>
      `;
    }

    async function pollTask() {
      if (!currentTaskId) return;
      const response = await fetch(`/api/task/${currentTaskId}`);
      const data = await response.json();
      if (!response.ok) {
        stopPolling();
        statusText.textContent = data.error || '查詢任務失敗';
        cancelBtn.disabled = true;
        return;
      }

      setProgress(data.progress || 0, data.message || data.status);

      if (data.status === 'completed') {
        stopPolling();
        cancelBtn.disabled = true;
        analyzeBtn.disabled = !file;
        exportJsonBtn.disabled = false;
        exportCsvBtn.disabled = false;
        renderResult(data.result || {});
      } else if (data.status === 'failed' || data.status === 'cancelled') {
        stopPolling();
        cancelBtn.disabled = true;
        analyzeBtn.disabled = !file;
        exportJsonBtn.disabled = true;
        exportCsvBtn.disabled = true;
        result.innerHTML = `<p class=\"error\">${data.error || data.message || '分析失敗'}</p>`;
      }
    }

    dropzone.addEventListener('click', () => videoInput.click());
    videoInput.addEventListener('change', () => setFile(videoInput.files[0] || null));

    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) setFile(e.dataTransfer.files[0]);
    });

    analyzeBtn.addEventListener('click', async () => {
      if (!file) return;
      const form = new FormData();
      form.append('video', file);

      analyzeBtn.disabled = true;
      cancelBtn.disabled = false;
      exportJsonBtn.disabled = true;
      exportCsvBtn.disabled = true;
      result.innerHTML = '';
      setProgress(0, '上傳中');

      try {
        const response = await fetch('/analyze', { method: 'POST', body: form });
        const data = await response.json();
        if (!response.ok) {
          analyzeBtn.disabled = !file;
          cancelBtn.disabled = true;
          result.innerHTML = `<p class=\"error\">${data.error || '發生錯誤'}</p>`;
          return;
        }

        currentTaskId = data.task_id;
        setProgress(data.progress || 1, data.message || '等待中');
        stopPolling();
        pollTimer = setInterval(pollTask, 1000);
        await pollTask();
      } catch (err) {
        analyzeBtn.disabled = !file;
        cancelBtn.disabled = true;
        result.innerHTML = `<p class=\"error\">分析失敗：${err.message}</p>`;
      }
    });

    cancelBtn.addEventListener('click', async () => {
      if (!currentTaskId) return;
      try {
        await fetch(`/api/task/${currentTaskId}/cancel`, { method: 'POST' });
      } catch (err) {
        result.innerHTML = `<p class=\"error\">取消失敗：${err.message}</p>`;
      }
    });

    exportJsonBtn.addEventListener('click', () => {
      if (currentTaskId) window.open(`/api/task/${currentTaskId}/export?format=json`, '_blank');
    });

    exportCsvBtn.addEventListener('click', () => {
      if (currentTaskId) window.open(`/api/task/${currentTaskId}/export?format=csv`, '_blank');
    });
  </script>
</body>
</html>
"""


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), FaceVideoHandler)
    stop_event = threading.Event()
    monitor = threading.Thread(target=_status_monitor, args=(stop_event,), daemon=True)
    monitor.start()
    _log(f"Server running at http://127.0.0.1:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("收到中斷訊號，準備關閉伺服器...")
    finally:
        stop_event.set()
        server.server_close()
        _log("伺服器已關閉")


if __name__ == "__main__":
    exit_code = 0
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        exit_code = 1
        _log(f"啟動失敗：{exc}")
        _wait_before_exit("程式已結束（發生錯誤）。按 Enter 鍵關閉視窗...")
    raise SystemExit(exit_code)
