"""다운로드 이벤트를 수집해 로컬 SSE로 흘려보내는 PoC용 addon.

주의: 최종 아키텍처에서 이 역할은 API 서버가 맡는다 (B.2 참고).

판별은 `responseheaders` 훅에서 내린다(본문 수신 전) — 다운로드가 아니면
`flow.response.stream = True`로 버퍼링·보류·이벤트를 전부 건너뛴다. 헤더가 브라우저로
나간 뒤에는 되돌릴 수 없으므로(제품 설계 6장), 여기서 내리는 판정이 최종 결정이다.
실제 보류·403 교체·이벤트 emit은 기존과 동일하게 `response` 훅에서 한다.
"""
import asyncio
import hashlib
import json
import os
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

# 규칙 3(크기 폴백) 제외 MIME — 브라우저가 자체 렌더링/해석하는 것들
_SIZE_FALLBACK_EXCLUDED_MIMES = {
    "text/html", "text/css", "text/javascript", "application/javascript",
    "application/json", "text/plain",
}
_SIZE_FALLBACK_EXCLUDED_PREFIXES = ("image/", "video/", "font/")

# A/B 비교 로그 — 스크래치패드 등 저장소 밖 경로를 환경변수로 받는다. 비어 있으면 로깅 안 함.
AB_LOG_PATH = os.environ.get("DASHBOARD_AB_LOG", "")


def _size_fallback_excluded(mime: str) -> bool:
    if mime in _SIZE_FALLBACK_EXCLUDED_MIMES:
        return True
    return any(mime.startswith(p) for p in _SIZE_FALLBACK_EXCLUDED_PREFIXES)


class Dashboard:
    def __init__(self):
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()

    # ── mitmproxy 훅 ──────────────────────────────────────────────
    def running(self):
        asyncio.get_running_loop().create_task(self._serve())
        if AB_LOG_PATH:
            print(f"[dashboard] A/B 판정 로그 → {AB_LOG_PATH}")

    def responseheaders(self, flow: http.HTTPFlow):
        # 대시보드 자신에 대한 요청은 판정도 로깅도 하지 않는다 (무한 루프 방지)
        if flow.request.port == DASHBOARD_PORT:
            return

        ev = self._evaluate(flow)
        if AB_LOG_PATH:
            self._log_ab(flow, ev)

        if not ev["decision_a"]:
            # 다운로드 아님 → 버퍼링·보류·이벤트 전부 없이 통과. 이 시점 이후로는 되돌릴 수 없다.
            flow.response.stream = True
            return

        # 다운로드 후보 → 버퍼 유지(기본값). response 훅에서 쓸 원본 헤더를 지금 스냅샷해 둔다.
        # (여기서 읽어야 나중에 403으로 교체된 뒤 mime_type이 오염되는 문제가 생기지 않는다)
        flow.metadata["dl_meta"] = {
            "mime_type": flow.response.headers.get("content-type", ""),
            "filename": self._filename(flow),
        }

    async def response(self, flow: http.HTTPFlow):
        if flow.request.port == DASHBOARD_PORT:
            return
        dl_meta = flow.metadata.get("dl_meta")
        if dl_meta is None:
            # responseheaders에서 다운로드 후보로 잡히지 않은 flow는 stream=True로 이미
            # 빠져나갔어야 한다. 정상 흐름에서는 여기 도달하지 않는다 — 안전장치로만 둔다.
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
            "filename": dl_meta["filename"],
            "mime_type": dl_meta["mime_type"],  # 403 교체 전 원본 헤더 — 오염되지 않는다
            "file_size": len(body),
            "sha256": sha256,
            "held_ms": round((time.perf_counter() - started) * 1000),
            "decision": "BLOCKED" if BLOCK else "RELEASED",
            "decision_source": "POLICY",
        })

    # ── 다운로드 판별 (MVP 기능 A) ────────────────────────────────
    def _evaluate(self, flow: http.HTTPFlow) -> dict:
        """Sec-Fetch-* 요청 맥락 + 응답 헤더로 판정한다. 본문은 쓰지 않는다
        (responseheaders 시점에는 없다 — 규칙 3의 크기 폴백은 Content-Length로만 가능하다).

        규칙 3에 대해 A안(Content-Length 있을 때만 크기 폴백)과 B안(크기 폴백 완전 폐기)을
        동시에 계산한다. 실제 판정에는 A안(decision_a)만 쓴다.
        """
        req_h = flow.request.headers
        res_h = flow.response.headers

        sec_fetch_mode = req_h.get("sec-fetch-mode")  # 헤더 자체가 없으면 None
        has_sec_fetch = sec_fetch_mode is not None

        is_attachment = "attachment" in res_h.get("content-disposition", "").lower()
        mime = res_h.get("content-type", "").split(";")[0].strip().lower()
        is_download_mime = mime in DOWNLOAD_MIMES

        cl_present = "content-length" in res_h
        try:
            cl_value = int(res_h.get("content-length", "0")) if cl_present else 0
        except ValueError:
            cl_present, cl_value = False, 0

        excluded = _size_fallback_excluded(mime)
        size_hit_a = cl_present and not excluded and cl_value >= MIN_DOWNLOAD_BYTES
        size_hit_b = False  # B안: 크기 폴백 자체를 폐기

        if has_sec_fetch and sec_fetch_mode == "navigate":
            # 다운로드 후보 (링크 클릭, <a download>, CD-only 파일). 전 규칙 적용
            context = "navigate"
            cd_trusted = True
            cors_only_mime = False
        elif has_sec_fetch and sec_fetch_mode == "cors":
            # XHR/fetch — 다운로드 MIME일 때만 인정 (CD·크기 신호 배제)
            context = "cors"
            cd_trusted = False
            cors_only_mime = True
        elif has_sec_fetch:
            # no-cors 및 그 외(same-origin, websocket 등) — 서브리소스 취급.
            # Content-Disposition 단독 신호는 신뢰하지 않는다 (Google anti-XSSI 오탐이 여기)
            context = sec_fetch_mode  # "no-cors" 또는 실측되지 않은 값 그대로 기록
            cd_trusted = False
            cors_only_mime = False
        else:
            # Sec-Fetch 헤더 없음 — 비브라우저 클라이언트/평문 HTTP 오리진. 기존 규칙 폴백
            context = "fallback"
            cd_trusted = True
            cors_only_mime = False

        if cors_only_mime:
            decision_a = decision_b = is_download_mime
            fired = "rule2_mime" if is_download_mime else ""
            fired_a = fired_b = fired
        else:
            cd_signal = is_attachment and cd_trusted
            decision_a = cd_signal or is_download_mime or size_hit_a
            decision_b = cd_signal or is_download_mime or size_hit_b
            if cd_signal:
                fired_a = fired_b = "rule1_content_disposition"
            elif is_download_mime:
                fired_a = fired_b = "rule2_mime"
            elif size_hit_a:
                fired_a, fired_b = "rule3_size_fallback", ""
            else:
                fired_a = fired_b = ""

        return {
            "context": context,
            "sec_fetch_mode": sec_fetch_mode or "",
            "content_length_present": cl_present,
            "content_length": cl_value,
            "mime": mime,
            "decision_a": decision_a,
            "decision_b": decision_b,
            "fired_rule_a": fired_a,
            "fired_rule_b": fired_b,
        }

    def _filename(self, flow: http.HTTPFlow) -> str:
        cd = flow.response.headers.get("content-disposition", "")
        if "filename=" in cd:
            return unquote(cd.split("filename=")[-1].strip('"; '))
        return urlparse(flow.request.pretty_url).path.rsplit("/", 1)[-1] or "(no name)"

    # ── A/B 비교 로그 (검증 전용, 저장소 밖 경로) ───────────────────
    def _log_ab(self, flow: http.HTTPFlow, ev: dict):
        parsed = urlparse(flow.request.pretty_url)
        record = {
            "ts": time.strftime("%H:%M:%S"),
            "host": flow.request.host,
            "path": parsed.path,  # 쿼리스트링 제외 — 프라이버시
            "method": flow.request.method,
            "sec_fetch_mode": ev["sec_fetch_mode"],
            "context": ev["context"],
            "content_length_present": ev["content_length_present"],
            "content_length": ev["content_length"],
            "mime_type": ev["mime"],
            "fired_rule_a": ev["fired_rule_a"],
            "fired_rule_b": ev["fired_rule_b"],
            "decision_a": ev["decision_a"],
            "decision_b": ev["decision_b"],
        }
        try:
            with open(AB_LOG_PATH, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

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
