import asyncio
from mitmproxy import http

BLOCK = False  # 데모용 토글 — 추후 판정 로직 결과로 교체


async def response(flow: http.HTTPFlow):
    # time.sleep()은 동기 블로킹 호출이라 mitmproxy의 단일 이벤트 루프 전체를 멈춰버려서
    # 이 프록시를 거치는 다른 모든 요청(다른 탭, 백그라운드 앱 등)이 직렬로 3초씩 밀리게 된다.
    # asyncio.sleep()으로 바꾸면 이 flow만 대기하고 다른 flow는 동시에 처리된다.
    await asyncio.sleep(3)
    if BLOCK:
        flow.response = http.Response.make(
            403, b"Blocked by malware detection platform", {"Content-Type": "text/plain"}
        )
