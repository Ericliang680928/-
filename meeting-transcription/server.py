"""會議記錄小幫手 — 選配後端：上傳音檔轉逐字稿。

純前端版（index.html）用瀏覽器麥克風即時轉錄，不需要這支程式。
若想「上傳錄音檔 → 轉成逐字稿」，再啟動這支小伺服器即可。

啟動：
    export OPENAI_API_KEY=sk-...           # 必填
    export OPENAI_TRANSCRIBE_MODEL=whisper-1   # 選填，預設 whisper-1
    python server.py                        # → http://127.0.0.1:8000

它做兩件事：
  1. 把本資料夾的靜態檔（index.html / style.css / app.js）服務出去
  2. 提供 POST /api/transcribe：收音檔 → 呼叫 OpenAI 轉錄 → 回傳 {"text": ...}

只用 Flask + 標準函式庫，不新增相依套件。
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
# 多數音檔格式上限約 25MB（OpenAI 限制）
MAX_BYTES = 25 * 1024 * 1024

app = Flask(__name__, static_folder=None)


# ---- 靜態頁面 ----
@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(HERE, filename)


# ---- 轉錄 API ----
@app.post("/api/transcribe")
def transcribe():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return jsonify(error="伺服器尚未設定 OPENAI_API_KEY 環境變數"), 500

    file = request.files.get("audio")
    if file is None or not file.filename:
        return jsonify(error="缺少音檔（欄位名稱應為 audio）"), 400

    raw = file.read()
    if not raw:
        return jsonify(error="音檔是空的"), 400
    if len(raw) > MAX_BYTES:
        return jsonify(error="音檔超過 25MB 上限，請先壓縮或分段"), 413

    language = (request.form.get("language") or "").strip()  # 例：zh、en（選填）
    filename = file.filename
    content_type = (
        file.mimetype
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )

    body, header_ct = _build_multipart(
        fields={"model": MODEL, **({"language": language} if language else {})},
        file_field="file",
        filename=filename,
        file_bytes=raw,
        file_ct=content_type,
    )

    req = urlrequest.Request(
        OPENAI_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": header_ct,
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return jsonify(text=data.get("text", ""))
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return jsonify(error=f"轉錄服務錯誤（{e.code}）", detail=detail), 502
    except URLError as e:
        return jsonify(error=f"無法連線到轉錄服務：{e.reason}"), 502


def _build_multipart(fields, file_field, filename, file_bytes, file_ct):
    """手刻 multipart/form-data，避免額外相依套件。"""
    boundary = "----mt" + uuid.uuid4().hex
    nl = b"\r\n"
    parts = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"'.encode()
        )
        parts.append(b"")
        parts.append(str(value).encode())
    parts.append(b"--" + boundary.encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {file_ct}".encode())
    parts.append(b"")
    body = nl.join(parts) + nl + file_bytes + nl
    body += b"--" + boundary.encode() + b"--" + nl
    return body, f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"會議記錄小幫手後端啟動 → http://127.0.0.1:{port}")
    print(f"轉錄模型：{MODEL}；OPENAI_API_KEY {'已設定' if os.environ.get('OPENAI_API_KEY') else '⚠️ 未設定'}")
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
