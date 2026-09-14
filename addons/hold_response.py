import time
from mitmproxy import http

BLOCK = False  # 데모용 토글 — 추후 판정 로직 결과로 교체


def response(flow: http.HTTPFlow):
    time.sleep(3)
    if BLOCK:
        flow.response = http.Response.make(
            403, b"Blocked by malware detection platform", {"Content-Type": "text/plain"}
        )
