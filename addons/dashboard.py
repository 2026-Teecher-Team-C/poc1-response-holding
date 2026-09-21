"""다운로드 이벤트를 수집해 로컬 SSE로 흘려보내는 PoC용 addon.

주의: 최종 아키텍처에서 이 역할은 API 서버가 맡는다 (B.2 참고).
"""
import asyncio
import hashlib
import json
import time
import uuid
from urllib.parse import unquote, urlparse

from mitmproxy import http

DASHBOARD_PORT = 8765
HOLD_SECONDS = 3
BLOCK = False  # PoC 1과 동일한 데모용 토글

# 다운로드로 볼 MIME (제품 설계 3장 "다운로드 판별")
DOWNLOAD_MIMES = (
    "application/octet-stream", "application/zip", "application/x-msdownload",
    "application/x-apple-diskimage", "application/vnd.microsoft.portable-executable",
)
MIN_DOWNLOAD_BYTES = 64 * 1024


class Dashboard:
    def __init__(self):
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()

    # ── mitmproxy 훅 ──────────────────────────────────────────────
    def running(self):
        asyncio.get_running_loop().create_task(self._serve())

    async def response(self, flow: http.HTTPFlow):
        # 대시보드 자신에 대한 요청은 이벤트로 만들지 않는다 (무한 루프 방지)
        if flow.request.port == DASHBOARD_PORT:
            return
        if not self._is_download(flow):
            return

        started = time.perf_counter()
        body = flow.response.content or b""
        sha256 = hashlib.sha256(body).hexdigest()

        await asyncio.sleep(HOLD_SECONDS)  # 판정 대기 자리 (PoC 3에서 실제 판정으로 교체)

        if BLOCK:
            flow.response = http.Response.make(
                403, b"Blocked by malware detection platform",
                {"Content-Type": "text/plain"},
            )

        self._emit({
            "event_id": str(uuid.uuid4()),
            "created_at": time.strftime("%H:%M:%S"),
            "request_host": flow.request.host,
            "url": flow.request.pretty_url,
            "filename": self._filename(flow),
            "mime_type": flow.response.headers.get("content-type", ""),
            "file_size": len(body),
            "sha256": sha256,
            "held_ms": round((time.perf_counter() - started) * 1000),
            "decision": "BLOCKED" if BLOCK else "RELEASED",
            "decision_source": "POLICY",
        })

    # ── 다운로드 판별 (MVP 기능 A) ────────────────────────────────
    def _is_download(self, flow: http.HTTPFlow) -> bool:
        headers = flow.response.headers
        if "attachment" in headers.get("content-disposition", "").lower():
            return True
        mime = headers.get("content-type", "").split(";")[0].strip().lower()
        if mime in DOWNLOAD_MIMES:
            return True
        return len(flow.response.content or b"") >= MIN_DOWNLOAD_BYTES

    def _filename(self, flow: http.HTTPFlow) -> str:
        cd = flow.response.headers.get("content-disposition", "")
        if "filename=" in cd:
            return unquote(cd.split("filename=")[-1].strip('"; '))
        return urlparse(flow.request.pretty_url).path.rsplit("/", 1)[-1] or "(no name)"

    # ── SSE 서버 ──────────────────────────────────────────────────
    def _emit(self, event: dict):
        self.events.insert(0, event)
        del self.events[200:]
        for q in list(self.subscribers):
            q.put_nowait(event)

    async def _serve(self):
        server = await asyncio.start_server(self._handle, "127.0.0.1", DASHBOARD_PORT)
        print(f"[dashboard] http://127.0.0.1:{DASHBOARD_PORT}")
        async with server:
            await server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await reader.readline()
            path = request_line.decode(errors="replace").split(" ")[1] if b" " in request_line else "/"
            while (await reader.readline()) not in (b"\r\n", b""):
                pass

            if path.startswith("/events"):
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                             b"Cache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n")
                queue: asyncio.Queue = asyncio.Queue()
                self.subscribers.add(queue)
                try:
                    for event in reversed(self.events):   # 접속 시 기존 이벤트부터
                        queue.put_nowait(event)
                    while True:
                        event = await queue.get()
                        writer.write(f"data: {json.dumps(event)}\n\n".encode())
                        await writer.drain()
                finally:
                    self.subscribers.discard(queue)
            else:
                page = PAGE.encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                             + f"Content-Length: {len(page)}\r\n\r\n".encode() + page)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()


PAGE = """<!doctype html><meta charset=utf-8><title>다운로드 이벤트</title>
<style>
 body{font:14px -apple-system,sans-serif;margin:2rem;color:#111}
 table{border-collapse:collapse;width:100%}
 th,td{padding:.5rem .6rem;border-bottom:1px solid #eee;text-align:left;white-space:nowrap}
 th{font-size:12px;color:#888;font-weight:500}
 .BLOCKED{color:#c00;font-weight:600} .RELEASED{color:#090}
 .hash{font-family:ui-monospace,monospace;font-size:12px;color:#888}
</style>
<h2>다운로드 이벤트 <small id=n style="color:#888;font-weight:400">0건</small></h2>
<table><thead><tr>
 <th>시각<th>파일명<th>호스트<th>크기<th>SHA-256<th>보류(ms)<th>판정
</tr></thead><tbody id=t></tbody></table>
<script>
const tbody = document.getElementById('t');
let count = 0;
new EventSource('/events').onmessage = (e) => {
  const d = JSON.parse(e.data);
  const kb = (d.file_size / 1024).toFixed(0).replace(/\\B(?=(\\d{3})+$)/g, ',');
  const row = document.createElement('tr');
  row.innerHTML = `<td>${d.created_at}<td>${d.filename}<td>${d.request_host}`
    + `<td>${kb} KB<td class=hash>${d.sha256.slice(0, 12)}…`
    + `<td>${d.held_ms}<td class=${d.decision}>${d.decision}`;
  tbody.prepend(row);
  document.getElementById('n').textContent = `${++count}건`;
};
</script>"""

addons = [Dashboard()]
