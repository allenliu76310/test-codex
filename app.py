from __future__ import annotations

import cgi
import json
import os
import tempfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

HOST = "0.0.0.0"
PORT = 5000
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


@dataclass
class PersonTrack:
    person_id: int
    embedding: np.ndarray
    appearances: int = 1


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denominator = (np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


def _face_embedding(face_gray: np.ndarray) -> np.ndarray:
    normalized = cv2.resize(face_gray, (64, 64), interpolation=cv2.INTER_AREA)
    embedding = normalized.astype(np.float32).flatten()
    mean = embedding.mean()
    std = embedding.std()
    if std < 1e-6:
        return embedding - mean
    return (embedding - mean) / std


def analyze_video(video_path: Path, frame_stride: int = 12, similarity_threshold: float = 0.86) -> dict:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)

    if detector.empty():
        raise RuntimeError("無法載入人臉偵測模型（Haar Cascade）。")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError("影片無法開啟，請確認檔案格式。")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    tracks: list[PersonTrack] = []
    frame_index = 0
    total_faces_detected = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % frame_stride != 0:
                frame_index += 1
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40),
            )

            for x, y, w, h in faces:
                roi = gray[y : y + h, x : x + w]
                embedding = _face_embedding(roi)
                total_faces_detected += 1

                if not tracks:
                    tracks.append(PersonTrack(person_id=1, embedding=embedding))
                    continue

                similarities = [_cosine_similarity(embedding, t.embedding) for t in tracks]
                best_idx = int(np.argmax(similarities))
                best_score = similarities[best_idx]

                if best_score >= similarity_threshold:
                    track = tracks[best_idx]
                    track.appearances += 1
                    # 輕微更新特徵向量，讓相似人臉匹配更穩定
                    track.embedding = (0.85 * track.embedding) + (0.15 * embedding)
                else:
                    tracks.append(
                        PersonTrack(person_id=len(tracks) + 1, embedding=embedding)
                    )

            frame_index += 1
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

    return {
        "video": video_path.name,
        "duration_seconds": round(duration_seconds, 2),
        "sampled_frames": frame_index // frame_stride + (1 if frame_index > 0 else 0),
        "faces_detected": total_faces_detected,
        "unique_people": len(tracks),
        "repeated_people": repeated_count,
        "people": people,
    }


class FaceVideoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._render_html().encode("utf-8"))

    def do_POST(self) -> None:
        if self.path != "/analyze":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        try:
            result = self._handle_upload_and_analyze()
            self._send_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"分析失敗：{exc}"})

    def _handle_upload_and_analyze(self) -> dict:
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
        if not file_item or not getattr(file_item, "filename", ""):
            raise ValueError("請上傳影片檔案。")

        filename = Path(file_item.filename).name
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支援的副檔名：{ext}。支援格式：{', '.join(sorted(ALLOWED_EXTENSIONS))}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            temp_file.write(file_item.file.read())
            temp_path = Path(temp_file.name)

        try:
            return analyze_video(temp_path)
        finally:
            if temp_path.exists():
                os.remove(temp_path)

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
    :root { color-scheme: light; }
    body { font-family: Arial, sans-serif; margin: 0; background: #f4f7fc; color: #1e293b; }
    .container { max-width: 920px; margin: 32px auto; background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }
    h1 { margin-top: 0; }
    .dropzone {
      border: 2px dashed #93c5fd;
      border-radius: 12px;
      padding: 30px;
      text-align: center;
      background: #eff6ff;
      transition: all 0.2s ease;
      cursor: pointer;
    }
    .dropzone.dragover { border-color: #2563eb; background: #dbeafe; }
    .meta { color: #475569; margin: 8px 0 0; }
    .btn {
      margin-top: 16px;
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 10px;
      padding: 10px 16px;
      font-size: 15px;
      cursor: pointer;
    }
    .btn:disabled { opacity: .6; cursor: not-allowed; }
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

    <button id=\"analyzeBtn\" class=\"btn\" disabled>開始分析</button>

    <div id=\"result\"></div>
  </div>

  <script>
    const dropzone = document.getElementById('dropzone');
    const videoInput = document.getElementById('videoInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const selectedFile = document.getElementById('selectedFile');
    const result = document.getElementById('result');

    let file = null;

    function setFile(f) {
      file = f;
      selectedFile.textContent = f ? `已選擇：${f.name}` : '尚未選擇檔案';
      analyzeBtn.disabled = !f;
    }

    dropzone.addEventListener('click', () => videoInput.click());
    videoInput.addEventListener('change', () => setFile(videoInput.files[0] || null));

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        setFile(e.dataTransfer.files[0]);
      }
    });

    analyzeBtn.addEventListener('click', async () => {
      if (!file) return;

      const form = new FormData();
      form.append('video', file);

      analyzeBtn.disabled = true;
      result.innerHTML = '<p>分析中，請稍候...</p>';

      try {
        const response = await fetch('/analyze', { method: 'POST', body: form });
        const data = await response.json();

        if (!response.ok) {
          result.innerHTML = `<p class=\"error\">${data.error || '發生錯誤'}</p>`;
          return;
        }

        const rows = data.people.map((p) => `
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
            <li>偵測到人臉次數：${data.faces_detected}</li>
            <li>辨識到不同人物數：${data.unique_people}</li>
            <li>重複出現人物數：${data.repeated_people}</li>
          </ul>
          <table>
            <thead><tr><th>人物</th><th>出現次數</th><th>是否重複出現</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="3">沒有偵測到人臉</td></tr>'}</tbody>
          </table>
        `;
      } catch (err) {
        result.innerHTML = `<p class=\"error\">分析失敗：${err.message}</p>`;
      } finally {
        analyzeBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), FaceVideoHandler)
    print(f"Server running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
