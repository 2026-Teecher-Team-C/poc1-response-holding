# PoC 1 — 응답 보류(Response Holding) 검증

이슈: [#1 PoC 1: 응답 보류(response holding) 검증](https://github.com/2026-Teecher-Team-C/poc1-response-holding/issues/1)

## 목적

전체 시스템 설계는 **"다운로드 응답을 헤더 전송 전에 붙잡아뒀다가, 판정이 끝난 뒤에 통과시키거나 차단할 수 있다"** 는 전제 위에 서 있다.
이 PoC는 그 전제를 mitmproxy 기반 프록시 addon으로 검증한다.

확인 대상:

1. 프록시로 응답 헤더 전송 타이밍을 제어할 수 있는가
2. 판정 지연(시뮬레이션 3초)이 다운로드 타임아웃 안에 들어오는가
3. 판정 결과에 따라 통과(원본 응답 그대로) / 차단(403) 분기가 가능한가

## 구성

| 파일 | 역할 |
|---|---|
| `Dockerfile` | `python:3.12-slim` + mitmproxy. 로컬 Python 버전 호환성 문제를 피하려고 컨테이너로 격리 (macOS/Linux 권장 경로) |
| `docker-compose.yml` | 8080 포트 매핑, `addons/`·`.mitmproxy/` 바인드 마운트 |
| `addons/hold_response.py` | 응답 보류 addon. `asyncio.sleep(3)` 후 `BLOCK` 값에 따라 403 차단 또는 통과 |
| `addons/dashboard.py` | Part B — 다운로드 이벤트 대시보드 addon. `hold_response.py`의 보류 기능을 포함한다. 판별은 `responseheaders` 훅(본문 수신 전, `Sec-Fetch-*` 요청 맥락 + 응답 헤더)에서 내리고, 다운로드가 아니면 `flow.response.stream = True`로 버퍼링·보류·이벤트를 전부 건너뛴다. 다운로드 후보만 `response` 훅에서 보류·403 교체·SSE 이벤트(`http://127.0.0.1:8765`)로 이어진다. 절차서 B.4 원본에서 재설계됐다(더 이상 byte-identical 아님) — 자세한 내용은 [다운로드 판별 재설계 실측](#다운로드-판별-재설계-실측-2026-09-21) 참고. **`hold_response.py`와 동시에 쓰지 않는다** |
| `testdata/sample.txt` | curl 재현용 텍스트 파일 (13KB, 체크섬 비교용) |
| `testdata/sample.zip` | 브라우저 다운로드 테스트용 zip (781B) — 이유는 [브라우저 실측 검증](#브라우저-실측-검증-macos-2026-09-15) 참고 |
| `requirements.txt` | mitmproxy 버전 고정 (`12.2.3` — Docker 검증에 쓰인 것과 동일 버전) |
| `windows/` | Docker 없이 Windows에 네이티브로 설치/실행/원복하는 PowerShell 스크립트 모음 |

### addon 동작

```python
BLOCK = False  # 데모용 토글 — 추후 판정 로직 결과로 교체

async def response(flow: http.HTTPFlow):
    await asyncio.sleep(3)
    if BLOCK:
        flow.response = http.Response.make(
            403, b"Blocked by malware detection platform", {"Content-Type": "text/plain"}
        )
```

mitmproxy의 `response` 훅은 **업스트림 응답을 다 받은 뒤, 클라이언트로 내려보내기 전에** 호출된다.
따라서 이 훅 안에서 대기하면 클라이언트는 헤더조차 받지 못한 채 기다리고, 훅이 끝난 시점에 통과 또는 교체된 응답을 받는다.

> ⚠️ **`time.sleep()`이 아니라 `asyncio.sleep()`을 써야 하는 이유** (이슈 원문 코드는 `time.sleep()`이었으나 실측 중 문제가 발견되어 수정함):
> mitmproxy는 단일 asyncio 이벤트 루프에서 모든 연결을 처리한다. `response` 훅을 동기 함수로 두고 그 안에서 `time.sleep()`(블로킹 호출)을 쓰면 **이벤트 루프 전체가 멈춰서, 이 프록시를 거치는 다른 모든 요청(다른 탭, 백그라운드 앱 등)이 3초씩 직렬로 밀린다.** 시스템 전역 프록시로 쓰면 브라우저의 모든 트래픽이 한 줄로 서서 하나씩 처리되므로, 동시 연결이 많을 때는 우리가 테스트하는 요청이 몇 분씩 지연되는("무한 로딩") 현상으로 나타난다. `response`를 `async def`로 선언하고 `await asyncio.sleep(3)`을 쓰면 이 flow만 대기하고 다른 flow는 이벤트 루프에서 동시에 처리된다.

## 실행 방법 (Docker)

```bash
docker compose build
docker compose up -d
docker compose logs -f       # "HTTP(S) proxy listening at *:8080." 확인
```

종료:

```bash
docker compose down
```

`BLOCK` 값을 바꾼 뒤에는 반드시 재시작:

```bash
docker compose restart
```

## 실행 방법 (Windows, Docker 없이 네이티브)

Docker Desktop/WSL2 설치가 부담스러운 팀원용 경로. **Python 3.9~3.12** 필요 (3.13+는 mitmproxy 호환성 미검증 — 이 프로젝트를 처음 만들 때 macOS의 Python 3.14 환경에서 mitmproxy 설치가 막혀서 Docker로 우회했던 것과 같은 이유).

```powershell
cd poc1-response-holding
.\windows\setup-venv.ps1      # venv 생성 + pip install -r requirements.txt
.\windows\run-mitmdump.ps1    # mitmdump 실행 (이 창은 열어둔 채로 둘 것)
```

`BLOCK` 값을 바꾼 뒤에는 `run-mitmdump.ps1`이 떠 있는 창에서 Ctrl+C로 종료했다가 다시 실행하면 된다.

### curl.exe로 재현 (시스템 설정 변경 불필요, 권장 — macOS의 curl 검증과 동일한 방식)

Windows 10/11에는 `curl.exe`가 기본 내장되어 있다. 별도 터미널에서:

```powershell
python -m http.server 8000 --directory testdata    # 터미널 1: 테스트 파일 서버

# 터미널 2
curl.exe -x 127.0.0.1:8080 http://localhost:8000/sample.txt -o downloaded_sample.txt `
     -w "http_code=%{http_code} time_total=%{time_total}s`n"
```

Windows 네이티브 실행은 mitmdump가 컨테이너가 아니라 호스트에서 직접 돌기 때문에 `host.docker.internal` 없이 `localhost`를 그대로 쓰면 된다.

### 브라우저 테스트용 시스템 프록시 + CA 인증서 설정/원복

시스템 전역 설정을 바꾸는 단계라 스크립트도 사용자가 **관리자 권한 PowerShell**에서 직접 실행해야 한다 (자동 실행하지 않음):

```powershell
# 관리자 권한 PowerShell에서
.\windows\setup-proxy.ps1        # 프록시 127.0.0.1:8080 설정 + CA 인증서 신뢰 등록
# HTTP만 테스트할 거면: .\windows\setup-proxy.ps1 -SkipCert

# ... 브라우저 테스트 (QUIC 우회 주의: chrome://flags/#enable-quic 비활성화 권장) ...

.\windows\revert-proxy.ps1       # 테스트 후 반드시 원복
```

`setup-proxy.ps1`은 `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer`를 신뢰할 수 있는 루트 인증 기관에 등록하고 사용자 프록시(레지스트리 `Internet Settings`)를 켠다. `revert-proxy.ps1`은 그 반대로 인증서를 삭제하고 프록시를 끈다. mitmproxy CA를 신뢰 상태로 남겨두면 그 CA로 서명된 모든 HTTPS를 브라우저가 믿게 되므로 테스트 후 원복은 필수다.

## curl 기반 재현 절차 (Docker, 시스템 설정 변경 불필요)

브라우저/시스템 프록시 없이 PoC 동작만 확인하는 경로다.

터미널 1 — 테스트용 정적 파일 서버 (QUIC을 쓰지 않는 HTTP/1.1 서버):

```bash
python3 -m http.server 8000 --directory testdata
```

터미널 2 — 프록시 경유 다운로드:

```bash
docker compose up -d

# BLOCK=False (기본값): 3초 지연 후 200 + 원본 파일
curl -x localhost:8080 http://host.docker.internal:8000/sample.txt \
     -o /tmp/downloaded_sample.txt \
     -w "http_code=%{http_code} time_total=%{time_total}s\n"

# BLOCK=True 로 바꾼 뒤
docker compose restart
curl -x localhost:8080 http://host.docker.internal:8000/sample.txt \
     -w "\nhttp_code=%{http_code} time_total=%{time_total}s\n"
```

> **왜 `host.docker.internal`인가?**
> mitmproxy가 컨테이너 안에서 돌기 때문에, 컨테이너 기준 `localhost`는 컨테이너 자신이다.
> 호스트에서 뜬 `python3 -m http.server 8000`에 닿으려면 `host.docker.internal`을 써야 한다
> (`docker-compose.yml`의 `extra_hosts: host.docker.internal:host-gateway`).
> 브라우저에서 시스템 프록시로 쓸 때는 이런 제약이 없고 일반 URL을 그대로 쓰면 된다.

## 검증 결과 (2026-09-14, 실측)

환경: macOS (Darwin 25.6.0, arm64), Docker 29.7.2 / Compose v5.4.0, 컨테이너 내 **mitmproxy 12.2.3** (Python 3.12).

### 기동 로그

```
[14:21:28.029] Loading script /addons/hold_response.py
[14:21:28.031] HTTP(S) proxy listening at *:8080.
```

### 기준선 — 프록시 미경유

```
$ curl http://localhost:8000/sample.txt -o /dev/null -w "http_code=%{http_code} time_total=%{time_total}s\n"
http_code=200 time_total=0.000884s
```

### 케이스 A — `BLOCK = False` (통과)

```
$ curl -x localhost:8080 http://host.docker.internal:8000/sample.txt -o /tmp/downloaded_sample.txt \
       -w "http_code=%{http_code} time_total=%{time_total}s size=%{size_download}\n"
http_code=200 time_total=3.013863s size=13248

$ shasum -a 256 testdata/sample.txt /tmp/downloaded_sample.txt
0c21d89c2f79946cd0a1ad5235f82541bc8ff86d62f7a1ec962629df5c87e148  testdata/sample.txt
0c21d89c2f79946cd0a1ad5235f82541bc8ff86d62f7a1ec962629df5c87e148  /tmp/downloaded_sample.txt
```

- 0.0009초 → **3.014초**. 지연이 addon에서 발생했음이 확인된다.
- 다운로드 파일 체크섬이 원본과 **완전히 동일** — 보류 후 통과시켜도 응답이 훼손되지 않는다.

mitmdump 플로우 로그 (지연이 응답 수신과 클라이언트 전달 사이에 있음을 보여줌):

```
[14:22:19.406][192.168.65.1:25831] client connect
[14:22:19.417][192.168.65.1:25831] server connect host.docker.internal:8000 (192.168.65.254:8000)
192.168.65.1:25831: GET http://host.docker.internal:8000/sample.txt HTTP/1.1
        << HTTP/1.0 200 OK 12.9k
[14:22:22.429][192.168.65.1:25831] server disconnect host.docker.internal:8000
[14:22:22.431][192.168.65.1:25831] client disconnect
```

업스트림 연결이 `:19.4`에 열렸고 클라이언트 전달 완료는 `:22.4` — 그 사이 약 3초가 보류 구간이다.

### 케이스 B — `BLOCK = True` (차단)

```
$ curl -x localhost:8080 http://host.docker.internal:8000/sample.txt -o /tmp/blocked_sample.txt \
       -w "http_code=%{http_code} time_total=%{time_total}s size=%{size_download}\n"
http_code=403 time_total=3.017229s size=37

$ cat /tmp/blocked_sample.txt
Blocked by malware detection platform
```

응답 헤더:

```
HTTP/1.1 403 Forbidden
Content-Type: text/plain
content-length: 37
```

- 3.017초 지연 후 **403**, 본문은 `Blocked by malware detection platform`.
- 원본 파일(13248바이트)은 클라이언트에 전혀 전달되지 않았다 (`size=37`).

### 성공 기준 대비

| 기준 | 결과 | 근거 |
|---|---|---|
| 다운로드 요청이 3초 지연됨 | 통과 | curl: 0.0009s → 3.014s / 3.017s · 브라우저(Chrome): 육안으로 약 3초 지연 확인 |
| `BLOCK=False`일 때 파일이 정상 저장됨 | 통과 | curl: 200, SHA-256 원본과 동일 · 브라우저: `sample.zip` 정상 다운로드 확인 |
| `BLOCK=True`일 때 403으로 차단됨 | 통과 | curl: 403 `Blocked by malware detection platform` · 브라우저: 동일 문구로 차단, 파일 미저장 확인 |
| 재현 가능하도록 리포에 기록/커밋 | 통과 | 이 리포 (`docker compose build && docker compose up -d` + curl 절차 + 아래 브라우저 절차) |

**결론: 응답 보류 전제는 유효하다.** 헤더 전송 전에 응답을 붙잡아둘 수 있고, 판정 결과에 따라 통과/차단 분기가 동작한다. curl(자동화 가능한 근거)과 실제 브라우저(사용자가 실제로 겪는 경험) 양쪽에서 동일하게 확인됐다.

### 아직 검증되지 않은 것

curl 기반 검증(위)에 이어 실제 브라우저 레벨 검증도 완료했다 (아래 [브라우저 실측 검증](#브라우저-실측-검증-macos-2026-09-15) 참고).
2026-09-21에 HTTPS 인터셉션, 실제 인터넷 오리진, 대용량 파일 메모리 버퍼링, 보류 상한 실측을
추가로 마쳤다 (아래 [HTTPS 인터셉션 및 보류 상한 실측](#https-인터셉션-및-보류-상한-실측-macos-2026-09-21) 참고). 남은 항목:

- 스트리밍 모드(`flow.response.stream`) 헤더 타이밍 — 지금까지는 전부 `stream=False`(전체 버퍼링)로만 검증했다
- Safari·Firefox의 보류 상한 (Chrome만 300초까지 확인)
- HTTPS에서의 보류 상한 (아래 실측은 전부 HTTP 오리진, `http.server` 기준)

## 수동 설정 가이드 (macOS) — 사용자가 직접 진행

> 아래는 **시스템 전역 설정을 바꾸는 작업**이라 자동화하지 않았다. 직접 수행해야 한다.
> PoC 확인이 끝나면 **프록시 설정과 CA 신뢰를 반드시 원복**할 것. 특히 HTTPS 프록시를 켠 채로 CA를 신뢰하지 않으면 **이 Mac에서 나가는 다른 모든 HTTPS 사이트가 깨진다** (아래 브라우저 실측 검증 참고).

### 1. CA 인증서를 키체인에 "항상 신뢰"로 등록 (HTTPS까지 테스트할 때만 필요)

컨테이너가 처음 기동되면 바인드 마운트를 통해 호스트에 CA 파일이 생성된다: `./.mitmproxy/mitmproxy-ca-cert.pem`

**GUI로 시도 시 자주 실패한다** — "관리자 이름과 암호를 입력하십시오" 창에서 올바른 관리자 암호를 넣어도 macOS Keychain Access가 원인 불명으로 실패하는 경우가 실측 중에도 있었다. 대신 터미널 명령을 권장한다:

```bash
cd poc1-response-holding
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain .mitmproxy/mitmproxy-ca-cert.pem
```

등록 여부 확인:
```bash
security find-certificate -c mitmproxy -a /Library/Keychains/System.keychain
```
(결과가 비어 있으면 등록 안 된 것)

HTTP만 테스트한다면 이 단계는 건너뛸 수 있다. (이번 실측도 HTTP만으로 전부 검증했고 이 단계는 시도하지 않았다.)

### 2. macOS 시스템 네트워크 프록시 설정

시스템 설정 → 네트워크 → **Wi-Fi**(또는 사용 중인 인터페이스) → 세부사항… → 프록시:

- **웹 프록시(HTTP)** 켜기 → 서버 `localhost`, 포트 `8080`
- **보안 웹 프록시(HTTPS)** 켜기 → 서버 `localhost`, 포트 `8080`
- 마지막에 **완료 → 적용**까지 눌러야 저장된다

터미널로 확인/토글도 가능:
```bash
networksetup -getwebproxy Wi-Fi
networksetup -setwebproxystate Wi-Fi off   # 원복
networksetup -setsecurewebproxystate Wi-Fi off
```

컨테이너가 8080을 호스트에 매핑하므로 브라우저 입장에서는 `localhost:8080`으로 보인다.

### 3. 브라우저 다운로드 테스트

⚠️ **`localhost`로 테스트 URL을 만들면 안 된다.** mitmproxy가 Docker 컨테이너 안에서 돌기 때문에, 브라우저가 `http://localhost:8000/...`으로 요청해도 컨테이너 입장에서 "localhost"는 컨테이너 자기 자신이라 Mac에 떠 있는 테스트 서버에 닿지 못하고 **무한 로딩**에 빠진다. 대신 Mac의 실제 LAN IP를 쓴다:

```bash
ipconfig getifaddr en0        # 예: 172.30.1.7
python3 -m http.server 8000 --directory testdata
```
→ 브라우저에서 `http://<위 IP>:8000/sample.zip` 로 접속 (curl 절차의 `host.docker.internal`과 동일한 이유의 문제이지만, 브라우저가 만드는 URL 자체를 바꿔야 하므로 `host.docker.internal`을 쓸 수 없다).

⚠️ 텍스트 파일(`sample.txt`)로 테스트하면 브라우저가 다운로드하지 않고 **화면에 바로 렌더링**한다 (정상 동작, PoC 실패 아님). "진짜 다운로드"를 보려면 `application/octet-stream`류 파일이 필요한데, **의미 없는 랜덤 바이트로 만든 테스트 파일은 Chrome이 "위험한 파일"로 자체 차단**할 수 있다 (엔트로피가 높아 악성코드 패커처럼 보이기 때문 — 우리 addon과 무관한 크롬 자체 판단). 그래서 `testdata/sample.zip`(정상적인 zip 아카이브)을 사용한다.

⚠️ Chrome은 QUIC(HTTP/3, UDP)으로 TCP 기반 프록시를 우회할 수 있다. 위처럼 로컬 `http.server`(HTTP/1.1)를 쓰면 애초에 QUIC 대상이 아니라서 문제없다.

`BLOCK=False`에서 3초 뒤 다운로드 시작 / `BLOCK=True`에서 403 표시 + 파일 미저장을 확인하면 브라우저 레벨 검증까지 완료된다.

### 4. 원복

```bash
networksetup -setwebproxystate Wi-Fi off
networksetup -setsecurewebproxystate Wi-Fi off
docker compose down
```
1단계에서 CA를 등록했다면 `sudo security delete-certificate -c mitmproxy /Library/Keychains/System.keychain` 로 제거.

## 브라우저 실측 검증 (macOS, 2026-09-15)

curl 기반 검증 이후, 실제 Chrome 브라우저로도 성공 기준 3개를 전부 확인했다. 과정에서 이슈 원문 코드/절차만으로는 안 드러나는 문제 3가지를 발견하고 고쳤다.

1. **Docker 컨테이너 안에서 `localhost`는 컨테이너 자신** — 브라우저로 `http://localhost:8000/...`을 열면 무한 로딩에 빠짐. Mac의 실제 LAN IP(`ipconfig getifaddr en0`, 이번엔 `172.30.1.7`)로 접속해서 해결 (위 3번 항목).
2. **`time.sleep()`이 mitmproxy 이벤트 루프 전체를 블로킹** — 시스템 프록시를 켜면 브라우저의 모든 트래픽(다른 탭, Discord 등 백그라운드 앱)이 이 프록시를 거치는데, 동기 `time.sleep(3)`이 그 전부를 한 줄로 세워 3초씩 직렬 처리하면서 우리 테스트 요청이 몇 초~몇 분씩 밀리는 "무한 로딩"으로 나타났다. `addons/hold_response.py`를 `async def response` + `await asyncio.sleep(3)`으로 수정해서 해결 — 이 flow만 대기하고 다른 flow는 동시 처리된다.
3. **랜덤 바이트 테스트 파일을 Chrome이 자체 차단** — 처음엔 `/dev/urandom`으로 만든 `sample.bin`(다운로드 강제를 위해 `application/octet-stream`으로 서빙)을 썼는데, 우리 addon이 아니라 **Chrome의 다운로드 보호 기능이 "위험한 파일"로 판단해 자체 차단**했다 (고엔트로피 데이터가 패킹된 악성코드와 비슷해 보이기 때문). `testdata/sample.zip`(정상 zip 아카이브)으로 교체해서 해결.

세 가지를 고친 뒤 최종 확인:

| 케이스 | 결과 |
|---|---|
| `BLOCK=False`, `http://172.30.1.7:8000/sample.zip` | 약 3초 지연 후 정상 다운로드 (스크린샷 확보) |
| `BLOCK=True`, 동일 URL | 약 3초 지연 후 403 "Blocked by malware detection platform", 파일 미저장 (스크린샷 확보) |

curl(자동 재현 가능한 근거)에 이어 브라우저(실제 사용자 경험)에서도 응답 보류 전제가 검증됐다.

## HTTPS 인터셉션 및 보류 상한 실측 (macOS, 2026-09-21)

CLAUDE.md에 정의된 이 저장소의 최우선 게이트 항목(HTTPS 인터셉션 미검증)을 닫는 실측이다.
`addons/hold_response.py`는 **한 줄도 고치지 않았다** — mitmproxy가 TLS를 종료하고 평문 flow를
그대로 `response` 훅에 넘겨주는지만 확인하는 것이 목적이므로, addon이 HTTPS를 의식할 필요가
없다는 것 자체가 검증 대상이다.

### 환경

```
Mitmproxy: 12.2.3
Python:    3.14.7
OpenSSL:   OpenSSL 4.0.1 9 Jun 2026
Platform:  macOS-26.6.2-arm64-arm-64bit-Mach-O
```

Docker가 아니라 **호스트에서 직접** `mitmdump`를 실행했다 (컨테이너 안 `~/.mitmproxy`와 호스트
키체인이 달라 변수가 하나 느는 것을 피하려는 선택). 의존성은 저장소 `.venv`에 설치.

CA는 새로 만들지 않고 2026-09-14 Docker 실행 때 생성된 저장소 `./.mitmproxy/`를 그대로 재사용했다:

```
sha1 Fingerprint=5A:A0:B7:4D:35:2E:26:33:23:5F:5D:1E:22:C3:CA:36:88:74:CE:64
subject=CN=mitmproxy, O=mitmproxy
notBefore=Sep 12 14:21:00 2026 GMT
notAfter=Sep  9 14:21:00 2036 GMT
```

### 재현 절차 (호스트 네이티브)

```bash
cd poc1-response-holding
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

mitmdump --set confdir=./.mitmproxy -s addons/hold_response.py
```

CA를 **로그인 키체인이 아니라 시스템 키체인**에 절대 경로로 등록 (사용자 직접 수행 — 시스템 전역
설정 변경이므로 자동화하지 않는다):

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain \
     "$(pwd)/.mitmproxy/mitmproxy-ca-cert.pem"
```

시스템 프록시는 건드리지 않고, Chrome은 격리 프로필로 띄워서 검증한다:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --user-data-dir=/tmp/poc-chrome \
    --proxy-server=127.0.0.1:8080 \
    --disable-quic
```

### A. HTTPS 인터셉션 — curl (실제 인터넷 오리진)

대상: `https://www.python.org/ftp/python/3.12.7/python-3.12.7-macos11.pkg` (45,387,635 bytes).
선정 이유: HTTPS 직링크, 리다이렉트 없이 200, `Content-Length` 명시, 피닝 없음.

탈락 후보: `https://get.videolan.org/vlc/3.0.21/macosx/vlc-3.0.21-arm64.dmg` — HEAD 요청이 302로
`http://ftp.kaist.ac.kr/...`(비-TLS 미러)로 넘어가 HTTPS 인터셉션 측정에 부적합했다. **피닝이나
HSTS 실패가 아니므로 `bypass_domains` 후보는 아니다.**

```
① 기준선 (프록시 미경유)
$ curl -o base.bin -w 'http=%{http_code} time=%{time_total} size=%{size_download}\n' "$URL"
http=200 time=3.899985 size=45387635
$ shasum -a 256 base.bin
2ec2355c1b3225ce1075fc1b562a6e113017aa6177df87c410667638c1574a09  base.bin

② 통과 (BLOCK=False, 프록시 경유)
$ curl -x http://127.0.0.1:8080 --cacert .mitmproxy/mitmproxy-ca-cert.pem \
    -o via.bin -w 'http=%{http_code} time=%{time_total} size=%{size_download}\n' "$URL"
http=200 time=7.845719 size=45387635
$ shasum -a 256 via.bin
2ec2355c1b3225ce1075fc1b562a6e113017aa6177df87c410667638c1574a09  via.bin

③ 차단 (BLOCK=True, 프록시 경유)
$ curl -x http://127.0.0.1:8080 --cacert .mitmproxy/mitmproxy-ca-cert.pem \
    -o blocked.bin -w 'http=%{http_code} time=%{time_total} size=%{size_download}\n' "$URL"
http=403 time=7.229562 size=37
$ cat blocked.bin
Blocked by malware detection platform
```

mitmdump 로그 — `CONNECT`로 끝나지 않고 `GET https://...`가 그대로 찍힌다. TLS를 종료하고
평문 flow를 훅에 넘겨준다는 직접 증거다:

```
[10:39:55.936][127.0.0.1:55717] client connect
[10:39:55.987][127.0.0.1:55717] server connect www.python.org:443 (151.101.192.223:443)
127.0.0.1:55717: GET https://www.python.org/ftp/python/3.12.7/python-3.12.7-… HTTP/2.0
     << HTTP/2.0 200 OK 43.3m
[10:40:03.781][127.0.0.1:55717] client disconnect
```

체크섬은 기준선·통과 양쪽 다 `2ec2355c1b3225ce1075fc1b562a6e113017aa6177df87c410667638c1574a09`로
동일 — HTTPS 응답을 붙잡았다가 통과시켜도 훼손되지 않는다.

### A-4. HTTPS 인터셉션 — Chrome 실측

`BLOCK=False` — 인증서 경고 없이 정상 다운로드:

```
127.0.0.1:56006: GET https://www.python.org/ftp/python/3.12.7/python-3.12.7-… HTTP/2.0
     << HTTP/2.0 200 OK 43.3m
```

`BLOCK=True`:

```
127.0.0.1:56021: GET https://www.python.org/ftp/python/3.12.7/python-3.12.7-… HTTP/2.0
     << HTTP/1.1 403 Forbidden 37b
```

- 화면 표시: `Blocked by malware detection platform`
- **`chrome://downloads`에 새 항목이 생기지 않는다.** "실패한 다운로드 항목이 남는 것"과
  "애초에 항목이 생기지 않는 것"의 차이이며, 이 프로젝트가 EDR·백신류(사후 탐지)와 갈리는
  지점이 바로 여기다 — 헤더 전송 전 보류이므로 브라우저 입장에서는 다운로드가 시작된 적이 없다.
- 같은 URL을 캐시 없이 재요청하려고 URL 뒤에 `?v=2`를 붙였다 (같은 URL 재시도 시 브라우저
  캐시로 요청 자체가 프록시까지 안 나갈 수 있다).

### A.6 보류 상한 — curl (대조군)

`asyncio.sleep` 값만 파라미터화한 측정 전용 addon으로 쟀다 (`hold_response.py`는 무수정 보존).
오리진은 로컬 `http.server` + `testdata/sample.zip`(781 bytes) — 전송 시간이라는 변수를 없애고
순수 보류 시간만 재기 위함이다.

```
hold=3   curl_rc=0 http=200 time=3.012619
hold=10  curl_rc=0 http=200 time=10.013706
hold=30  curl_rc=0 http=200 time=30.014502
hold=60  curl_rc=0 http=200 time=60.013046
hold=120 curl_rc=0 http=200 time=120.013468
hold=300 curl_rc=0 http=200 time=300.013559
```

6구간 전부 통과. 서버 측 훅 로그도 전 구간 `ENTER → EXIT elapsed=N.00s`로 완주했다. **curl은
기본 응답 타임아웃이 없어 상한을 정하지 않는다 — 즉 이 대조군에서 상한을 정하는 쪽은 서버가
아니라 클라이언트다.**

### A.6 보류 상한 — Chrome

`HOLD_SECONDS=300`, `http://10.96.203.230:8000/sample.zip`:

```
[11:01:30.567][127.0.0.1:55909] client connect
[11:01:30.572][127.0.0.1:55909] server connect 10.96.203.230:8000
[probe] ENTER  hold=300.0s wall=11:01:32 url=http://10.96.203.230:8000/sample.zip
[11:01:32.931][127.0.0.1:55909] server disconnect 10.96.203.230:8000
[probe] EXIT   hold=300.0s wall=11:06:32 elapsed=300.00s url=http://10.96.203.230:8000/sample.zip
127.0.0.1:55909: GET http://10.96.203.230:8000/sample.zip HTTP/1.1
     << HTTP/1.0 200 OK 781b
```

- 이 연결에 `client disconnect`가 없다 → **Chrome은 300초를 포기하지 않았다.**
- 저장된 파일 무결성 확인: 원본 SHA-256 `30c56161423e0e9d571815efc4335d691694985e631853c5ef7e1501f7fe09d3`,
  `~/Downloads/sample.zip` 동일.
- **결론: Chrome 기준 보류 상한은 300초 초과(T > 300s). 5분까지는 검사 파이프라인의 제약이
  아니다.** 단 Safari·Firefox는 미측정이고, HTTPS에서 이 값이 달라질 가능성도 미검증이다.

### 부수 발견

1. **`stream=False`라 보류가 다운로드 시간 위에 얹힌다.** 기준선 3.899985s vs 프록시 경유
   7.845719s — 45MB를 전부 메모리에 버퍼링한 뒤에야 `response` 훅이 불린다. 사용자 체감 지연은
   `다운로드 시간 + 검사 시간`이 된다. 위 "아직 검증되지 않은 것"의 메모리 버퍼링 항목에 대한
   실측치다.
2. **보류 중 실제로 열려 있는 건 프록시↔브라우저 구간뿐이다.** 훅 진입 직후 `server disconnect`
   가 찍힌다 — 오리진 연결은 이미 닫혀 있다. 즉 검사 시간 예산에서 오리진 타임아웃은 제약이
   아니다. 단, 이번 오리진은 응답 후 즉시 연결을 닫는 HTTP/1.0 `http.server`였고, keep-alive를
   쓰는 실제 CDN에서도 동일한지는 미확인이다.
3. **`BLOCK = True`는 다운로드만이 아니라 프록시를 경유하는 모든 응답을 차단한다.** 해당 세션
   로그에 403이 30건 찍혔다. PoC 1에는 다운로드 여부 판별이 없기 때문이며, 그 자리가 Part B의
   `_is_download()`다. PoC 1 단계의 알려진 한계로 남겨둔다.
4. **TLS 핸드셰이크 실패는 관측됐지만 재현되지 않았다 — 피닝으로 단정할 수 없다.**
   CA 등록 직후인 11:01 세션에서 Chrome의 백그라운드 통신이
   `Client TLS handshake failed. The client does not trust the proxy's certificate`로
   49건 실패했다 (`accounts.google.com`, `clients2.google.com`, `update.googleapis.com`,
   `www.gstatic.com`, `safebrowsing.googleapis.com`, `chrome.google.com`,
   `android.clients.google.com`, `clientservices.googleapis.com`,
   `optimizationguide-pa.googleapis.com`).

   처음에는 Chrome 자체 인증서 피닝으로 판단했으나, **이후 세션에서 같은 도메인이 통과하면서
   그 판단이 뒤집혔다.**

   | 세션 | 시각 | `does not trust the proxy's certificate` 실패 |
   |---|---|---|
   | A.6 Chrome (측정용 addon) | 11:01 | 49건 |
   | A-4 통과 (`BLOCK=False`) | 11:09 | 1건 |
   | A-4 차단 (`BLOCK=True`) | 11:11 | 0건 |
   | 파일 호스팅 도메인 확인 | 11:18 | 0건 |

   11:18 세션에서 `accounts.google.com`은 3회 등장해 **실패 0건**, `www.gstatic.com`은 25회
   등장해 실패 1건이었다. 같은 세션의 실패 3건은 문구 자체가 다르다 —
   `The client disconnected during the handshake`(클라이언트가 핸드셰이크 도중 끊음, 탭 이동 등)
   로, 신뢰 실패와 원인이 다르다.

   **11:01의 실패 원인은 확정하지 못했다.** CA를 시스템 키체인에 등록한 직후 Chrome을 띄운
   타이밍과 관련이 있어 보이나 근거가 없으므로 추측을 기록하지 않는다. 재현되면 그때 원인을
   규명한다.

5. **Google 파일 호스팅 도메인은 인터셉션된다 — `bypass_domains` 후보가 아니다.**
   위 4번 때문에 "Google 도메인을 통째로 바이패스해야 하나"가 쟁점이 됐다. 만약
   `drive.google.com`이 피닝돼 있다면 실제 악성코드 유포 경로 하나가 검사 없이 통과한다는
   뜻이므로 별도로 확인했다.

   ```
   127.0.0.1:56175: GET https://drive.google.com/ HTTP/2.0
   127.0.0.1:56219: GET https://dl.google.com/chrome/mac/universal/stable/GGRO/… HTTP/2.0
   127.0.0.1:56223: GET https://storage.googleapis.com/ HTTP/2.0
   ```

   | 도메인 | Chrome 결과 |
   |---|---|
   | `drive.google.com` | 인증서 경고 없이 정상 표시 |
   | `dl.google.com` | 설치 파일 다운로드 시작됨 |
   | `storage.googleapis.com` | GCS가 `MissingSecurityHeader` XML 반환, Chrome이 본문 렌더링 |

   `storage.googleapis.com`의 XML 오류는 인증 없이 버킷 목록을 요청했을 때의 GCS 정상 응답이다.
   중요한 건 **응답 본문이 프록시를 통과해 브라우저 화면에 닿았다는 것**이다. 세 도메인 모두
   평문 요청 라인이 찍혔고 핸드셰이크 실패는 0건이다.

   **결론: 이 PoC에서 피닝으로 확인된 도메인은 없다. `bypass_domains` 초기 데이터 후보는
   현재 비어 있다.** 다만 바이패스 목록을 만들 때 `*.google.com` 같은 와일드카드를 쓰면
   `drive.google.com`이 함께 빠져 검사 구멍이 되므로, 정확한 호스트명 단위로만 등록해야 한다.

### 알려진 함정 (Part A에서 추가로 밟은 것)

- **CA를 상대 경로로 키체인에 등록하면 `Error reading file`이 난다.**
  `security add-trusted-cert -k ... .mitmproxy/mitmproxy-ca-cert.pem`처럼 상대 경로를 쓰면 실행
  셸의 cwd가 저장소 루트가 아닌 순간 조용히 실패한다. 항상 절대 경로(`$(pwd)/...`)로 등록할 것.
- **같은 URL을 재요청하면 캐시 때문에 프록시까지 요청이 안 나갈 수 있다.** 재현 시 URL 뒤에
  `?v=2` 같은 더미 쿼리를 붙여 캐시를 우회한다.

curl(자동 재현 가능한 근거)과 브라우저(실제 사용자 경험) 양쪽에서 HTTPS 인터셉션이 HTTP와
동일하게 동작함을 확인했다. **PoC 1의 최우선 게이트 항목(HTTPS 미검증)이 닫혔다.**

## 다운로드 이벤트 대시보드 검증 (2026-09-21)

> ⚠️ **대시보드는 PoC 전용 구조다.** 최종 아키텍처는 `에이전트 → gRPC → API 서버 → SSE → 콘솔`이며,
> 이 addon이 직접 여는 로컬 HTTP 서버(`http://127.0.0.1:8765`)는 그 자리를 임시로 대신하는 것뿐이다.
> 이 PoC 코드를 그대로 최종 에이전트에 남기면 로컬 에이전트가 웹 서버를 품게 되어
> CLAUDE.md의 "로컬 에이전트는 파일 내용을 파싱하지 않는다 / 공격 표면 최소화" 원칙과 충돌한다.
> `_is_download()`의 판별 로직과 이벤트 필드 스키마만 상위 설계로 옮기고, 서버 코드 자체는
> 옮기지 않는다.

Part A(HTTPS 인터셉션)에 이어 절차서 `2026-09-21-poc-https-and-dashboard.md`의 Part B를 검증했다.
`addons/dashboard.py`는 절차서 B.4 코드와 **byte-identical** (`diff` 무출력, `ast.parse` 통과) —
의도적인 변경은 없다. 판별 로직이 허술한 부분이 이번 검증에서 드러나지만, 이는 **고칠 대상이
아니라 측정 결과**다.

### 생성물

`addons/dashboard.py` — `hold_response.py`의 보류 기능을 포함하므로 **`hold_response.py`와
동시에 쓰지 않는다** (동시에 쓰면 보류가 두 번 걸린다).

```bash
.venv/bin/mitmdump -s addons/dashboard.py -p 8080 --set confdir=./.mitmproxy
# 대시보드: http://127.0.0.1:8765
```

검증은 브라우저 화면이 아니라 `curl -N http://127.0.0.1:8765/events`로 SSE 스트림을 직접
캡처해 JSON 필드값을 그대로 판정하는 방식으로 진행했다 (필드값이 원문으로 남아 증거력이 높다).

### 검증 기준 6건 (절차서 B.5)

| # | 기준 | 판정 |
|---|---|---|
| 1 | 다운로드 1건 → 이벤트 1건 | 통과 |
| 2 | 일반 웹서핑에 행이 생기지 않음 | **실패** |
| 3 | `BLOCK=True` → `BLOCKED`/403 | 통과 (단 `mime_type` 오염 발견) |
| 4 | 동시 3건이 서로 지연되지 않음 | 통과 |
| 5 | SSE 구독자 2개가 같은 스트림 수신 | 통과 |
| 6 | HTTPS 다운로드 | 통과 |

#### 기준 1 — SSE 캡처 원문

```
data: {"event_id": "cae88a2c-...", "created_at": "11:29:07", "request_host": "127.0.0.1", "url": "http://127.0.0.1:8000/sample.zip?t=criterion1", "filename": "sample.zip", "mime_type": "application/zip", "file_size": 781, "sha256": "30c56161...", "held_ms": 3002, "decision": "RELEASED", "decision_source": "POLICY"}
```

#### 기준 3 — 차단 + `mime_type` 오염

curl `403`, 바디 `Blocked by malware detection platform`. 이벤트:

```
{"filename": "sample.zip", "mime_type": "text/plain", "file_size": 781, "sha256": "30c56161...", "held_ms": 3003, "decision": "BLOCKED", "decision_source": "POLICY"}
```

원본 zip의 `application/zip`이 아니라 403 교체 응답의 `text/plain`이 기록됐다. 원인은 코드
순서다 — `flow.response = http.Response.make(...)`로 응답을 교체한 **뒤에** `_emit()`이
`flow.response.headers`를 읽는다 (`addons/dashboard.py:48-60`). **`BLOCKED` 이벤트의
`mime_type`은 구조적으로 항상 오염되며, 차단된 파일이 원래 무엇이었는지가 기록에서 사라진다.**
상위 ERD로 옮길 때 반드시 인지해야 할 지점이다. (코드는 고치지 않았다)

#### 기준 4 — 동시 3건

```
held_ms = 3004 / 3003 / 3002
curl time_total = 3.016 ~ 3.019s
```

3초/6초/9초로 누적되지 않았다 → 직렬화 아님. `asyncio.sleep` 논블로킹 확인.

#### 기준 5 — SSE 다중 구독

`curl -N /events` 2개를 동시에 열고 다운로드 1건 트리거 → 두 캡처 파일 `diff` 결과 완전 동일
(접속 시 과거분 3건 replay + 신규 1건).

#### 기준 6 — HTTPS

```
{"request_host": "www.python.org", "filename": "python-3.12.7-macos11.pkg", "mime_type": "application/octet-stream", "file_size": 45387635, "sha256": "2ec2355c...", "held_ms": 3040, "decision": "RELEASED", "decision_source": "POLICY"}
```

### 기준 2 — 실패: 판별 로직이 상위 설계로 올라가야 한다는 측정 결과

프록시를 켠 Chrome으로 **약 4분간 일반 웹서핑**(검색, GitHub 문서 열람, YouTube, 앱스토어
페이지)을 했다. **다운로드는 한 건도 하지 않았다.**

```
총 이벤트           139건
실제 다운로드 MIME    0건
크기                최소 18B / 중앙값 82,980B / 최대 1,628,854B
64KB 미만인데 이벤트가 된 건   59건
```

발동 규칙별 (`_is_download()` 역산):

```
80건  규칙 3 — len(body) >= 64KB
59건  규칙 1 — Content-Disposition: attachment
 0건  규칙 2 — DOWNLOAD_MIMES 일치
```

MIME 타입별:

```
46건  text/javascript
40건  application/json
20건  application/javascript
12건  text/css
 8건  text/html
 8건  image/png
 3건  text/plain
 1건  application/x-protobuffer
 1건  image/webp
```

호스트별:

```
78건  www.google.com
30건  github.githubassets.com
 8건  www.gstatic.com
 8건  camo.githubusercontent.com
 6건  www.youtube.com
 3건  ep1.adtrafficquality.google
 2건  github.com
 2건  play.google.com
 1건  encrypted-tbn0.gstatic.com
 1건  googleads.g.doubleclick.net
```

**핵심 발견 — `Content-Disposition: attachment`는 다운로드 신호가 아니다.**
59건은 크기가 18~459바이트인데도 이벤트가 됐다. 익명화한 표본(URL 경로는 남기되 쿼리
파라미터는 잘라냈다):

```
size=19   filename='f.txt'   경로=/async/ddljson
size=18   filename='f.txt'   경로=/async/newtab_promos
size=168  filename='f.txt'   경로=/complete/search   (쿼리에 xssi=t 포함)
```

URL 경로 어디에도 `f.txt`가 없다 → `filename`이 `Content-Disposition` 헤더에서 온 것이다.
즉 **Google이 18바이트 JSON API 응답에 `Content-Disposition: attachment; filename="f.txt"`를
붙이고 있다.** 브라우저가 응답을 렌더링하거나 MIME 스니핑하지 못하게 막는 보안 하드닝
(anti-XSSI) 기법이며, 요즘 API에서 흔하다. 절차서가 **가장 신뢰할 만한 다운로드 신호로 쓴
헤더가 실제로는 다운로드와 무관**하다는 뜻이므로, 크기 폴백만 조여서 해결되는 문제가 아니다.

**오탐은 행만 늘리는 게 아니다 — 웹서핑이 느려진다.**
`dashboard.py`는 `판별 → 3초 보류 → 이벤트` 순서다. 따라서 139건이 **전부 3초씩 지연됐다.**
검색 한 번에 JS 번들 수십 개가 3초씩 밀린다. 오탐은 DB 오염 이전에 **사용성 문제**다.

**규모.** 4분에 139건 ≈ 시간당 약 2,000행, 8시간 근무 기준 장비 한 대당 약 16,000행. 각 행에
URL 전문이 들어간다. 상위 ERD 6장이 우려한 "`download_events`가 브라우징 이력 DB가 된다"가
수치로 확인된 지점이다.

### `download_events` 필드 NULL 감사 (절차서 B.7)

| 필드 | 실제 값 | 비고 |
|---|---|---|
| `event_id` | 항상 채워짐 (UUID) | |
| `created_at` | 항상 채워짐 (`HH:MM:SS`) | 날짜가 없어 자정을 넘기면 정렬이 모호해진다 |
| `request_host` | 항상 채워짐 | |
| `url` | 항상 채워짐 (쿼리스트링 포함 전문) | 보존·마스킹 정책 필요 |
| `filename` | 거의 항상 채워짐. 경로가 `/`로 끝나면 `"(no name)"` | 공격자가 정한 값 — 표시만, 경로로 쓰지 않는다 |
| `mime_type` | **실제로 NULL이 나오는 유일한 칸** — `Content-Type`이 없으면 빈 문자열. `BLOCKED` 건에서는 위 오염 버그 | |
| `file_size` | **항상 채워짐** | 절차서 B.3/B.7은 "chunked면 `Content-Length`가 없어 NULL 우려"라고 적었으나, 실제 B.4 구현은 헤더를 안 쓰고 `len(flow.response.content)`(버퍼 실제 바이트)를 쓴다. chunked 응답에서도 정확한 바이트 수가 기록됐다. **절차서 본문과 구현 코드의 불일치**이며, 구현 쪽이 더 견고하다 |
| `sha256` | 항상 채워짐 | |
| `held_ms` | 항상 채워짐 (3000~3040ms) | |
| `decision` | 항상 `RELEASED`/`BLOCKED` | |
| `decision_source` | 항상 `POLICY` (하드코딩) | PoC라 의도된 것 |

### 결론

통과한 4건(동시성, SSE 다중 구독, HTTPS, 필드 스키마 대체로 견고)과 기준 3의 `mime_type`
오염, 기준 2의 실패를 함께 보면: **SSE 스트리밍과 이벤트 스키마 자체는 상위 서버로 옮길
준비가 됐지만, `_is_download()` 판별 로직은 PoC 수준을 벗어나지 못했다.** 특히
`Content-Disposition: attachment` 단독 신호는 신뢰할 수 없다는 것이 이번 실측의 핵심
결과이며, 상위 설계의 다운로드 판별 로직에 반영되어야 한다.

## 다운로드 판별 재설계 실측 (2026-09-21)

위 절의 139건 오탐을 닫기 위해 `docs/2026-09-21-next-detection-redesign.md` 절차서에 따라
판별 로직을 `responseheaders` 훅으로 옮기고 `Sec-Fetch-*` 기반 맥락 규칙으로 재설계한 뒤
재실측했다.

### 구현 구조 변경

```
responseheaders 훅   요청 맥락(Sec-Fetch-*) + 응답 헤더로 판정 (본문 없음)
   다운로드 아님 → flow.response.stream = True   버퍼링·보류·이벤트 전부 없음
   다운로드     → 버퍼 유지, response 훅으로 진행

response 훅         보류 → 판정 → 릴리스/403 → 이벤트 emit
```

**헤더가 브라우저로 나간 뒤에는 보류도 차단도 불가능하므로, `responseheaders`에서 내리는 판정은
최종 결정이다.** "일단 흘려보내고 나중에 승격"은 성립하지 않는다.

### 측정 조건

프록시를 켠 Chrome 별도 프로필(`--proxy-bypass-list="<-loopback>" --disable-quic`)로 테스트
다운로드 ①②③④를 각 1회 클릭한 뒤, **다운로드 없이 약 4분간 일반 웹서핑**(검색·GitHub·YouTube·
Reddit 등). 세션 전체 응답 1,152건.

기동:

```bash
.venv/bin/mitmdump -s addons/dashboard.py -p 8080 --set confdir=./.mitmproxy
```

### 구 규칙 대비

```
구 규칙(절차서 B.4)  약 78건   ← 같은 세션 데이터에 소급 적용. 로그에 Content-Disposition이
                                 일부만 남아 하한선이다
신 규칙(A안)          20건
```

직전 측정([위 절](#다운로드-이벤트-대시보드-검증-2026-09-21), 구 규칙 실측)에서는 4분 웹서핑에
139건이었다.

### 이벤트 20건의 내역

| 건수 | 정체 | 성격 |
|---|---|---|
| 4 | 테스트 다운로드 ①②③④ | 의도한 탐지 |
| 13 | Chrome 자동 업데이트 (`edgedl.me.gvt1.com`, `clients2.googleusercontent.com`, `r3---sn-3u-bh2ly.gvt1.com`) | 진짜 파일 다운로드. 오탐 아님 |
| 1 | `clients2.google.com` anti-XSSI | 오탐 |
| 1 | `safebrowsing.googleapis.com` | 오탐 |
| 1 | `www.reddit.com` | 오탐 |

**순수 오탐 3건.**

### 맥락별 전체 응답 분포

```
550건  no-cors
536건  cors
 34건  navigate
 14건  fallback
 12건  same-origin
```

### 발동 규칙별 (A안, 다운로드로 판정된 20건)

```
14건  rule1_content_disposition
 4건  rule2_mime
 2건  rule3_size_fallback
```

### 오탐 3건의 원인 — 각각 다른 구멍이다

**① `safebrowsing.googleapis.com`**

```
application/x-protobuf   8,679,999 bytes   ctx=no-cors   rule3_size_fallback
path=/v4/threatListUpdates:fetch
```

Chrome Safe Browsing 위협 DB 업데이트. `application/x-protobuf`가 규칙 3의 제외 MIME 목록에
없어 크기 폴백에 걸렸다.

**② `www.reddit.com`**

```
application/octet-stream   ctx=cors   rule2_mime
path=/svc/shreddit/compression-dictionaries/br/dict-a6e9d3b5...
```

Reddit이 Brotli 압축 사전을 `application/octet-stream`으로 fetch 받는다. `cors` 분기의
"다운로드 MIME일 때만 인정" 규칙을 정확히 통과한다. **`octet-stream`이 곧 다운로드라는 전제가
깨지는 사례다.**

**③ `clients2.google.com`**

```
application/json   80 bytes   filename="json.txt"   ctx=fallback
```

anti-XSSI 패턴. `Sec-Fetch`가 없는 폴백 경로라 맥락 필터가 걸리지 않는다.

### Chrome 자동 업데이트 13건 — 오탐이 아니지만 설계 쟁점이다

```
/edgedl/release2/chrome_component/V3P1l2hLvLw_7/7_all_sslErrorAssistant.crx3
/edgedl/diffgen-puffin/ceofaddefefcbblgcgnibnonglccbfja/f1eb9ab2...
/edgedl/chromewebstore/.../1.0.0.6_nmmhkkegccagdldgiimedpiccmgmieda.crx
```

`gvt1.com`은 Chrome이 컴포넌트·확장 업데이트를 받는 CDN이다. 전부 `ctx=fallback`(Chrome 네트워크
서비스가 직접 보내는 요청이라 `Sec-Fetch`가 없다).

**진짜 파일 다운로드이므로 판별 규칙은 정상 동작한 것이다.** 다만 두 가지 함의가 있다:

- 사용자가 아무것도 하지 않아도 이벤트가 생기므로 **검증 기준 1의 "이벤트 0건"은 달성 불가능한
  목표다**
- fail-close 정책상 검사 서버에 닿지 못하면 이들이 차단된다 → **Chrome의 보안 업데이트와 Safe
  Browsing 위협 DB 갱신이 조용히 막힌다.** 악성코드를 막으려다 브라우저의 방어 기능을 끄는
  결과가 될 수 있다

→ `bypass_domains`의 첫 실제 후보이며, 인증서 피닝과는 **사유가 다르다**(브라우저 자체 업데이트
인프라). 스키마에 사유 구분이 필요할 수 있다.

### A안 vs B안 — A안 채택

```
A안(Content-Length가 있을 때만 크기 폴백)  20건
B안(크기 폴백 폐기)                        18건
두 안이 갈린 건                             2건
   clients2.googleusercontent.com  application/x-chrome-extension    161,196  ctx=no-cors
   safebrowsing.googleapis.com     application/x-protobuf          8,679,999  ctx=no-cors
```

갈린 2건이 모두 사용자 다운로드가 아니고, 테스트 다운로드 ①②③④는 넷 다 규칙 3 없이 탐지됐다.
**정상 트래픽만 보면 B안이 유리해 보인다.**

**그럼에도 A안을 채택한다.** 근거:

- 이 비교는 정상 트래픽만 본 것이다. 공격자는 자기 서버를 통제하므로 `Content-Disposition`을
  붙이지 않고 `Content-Type`을 제외 목록에 없는 값으로 주면 된다. B안에서는 규칙 1·2가 걸리지
  않고 크기 폴백도 없어 **그 다운로드가 관측되지 않는다.** A안은 크기 폴백으로 잡는다
- 못 잡는 비용(악성코드가 디스크에 닿음)과 잘못 잡는 비용(3초 지연 + 행 하나)은 대칭이 아니다
- CLAUDE.md의 fail-close 고정 결정과 같은 방향이다. 판별에서만 "확신 없으면 흘려보낸다"를 쓰면
  일관성이 깨진다
- 측정된 비용은 1,152건 중 2건이다

**A안의 한계도 함께 기록한다:** 규칙 3의 제외 목록은 블록리스트다. 공격자가 `image/png`나
`text/html`로 위장하면 A안에서도 크기 폴백을 피해간다. A안이 B안보다 넓게 잡는 범위는 "제외
목록에 없는 비렌더링 MIME"뿐이다. 제외 목록을 화이트리스트 방향으로 뒤집는 설계는 상위 검토
대상이다.

### 검증 기준 6건 판정 (지시서 기준)

| # | 기준 | 판정 |
|---|---|---|
| 1 | 일반 웹서핑 4분 → 이벤트 0건 | **부분 달성** — 20건(순수 오탐 3건). 구 규칙 139건 대비. 0건은 Chrome 자동 업데이트 때문에 달성 불가능한 목표였다 |
| 2 | 다운로드 ①②③④ 전부 탐지 | **통과** — 4건 전부 |
| 3 | 비다운로드 트래픽 지연 없음 | **통과** — 사용자 체감 확인("빠릿했다"). 구 규칙에서는 서브리소스가 건당 3초씩 밀렸다 |
| 4 | 45MB HTTPS 다운로드 | **통과** — `http=200 size=45387635 time=7.633714s`, SHA-256 `2ec2355c1b3225ce1075fc1b562a6e113017aa6177df87c410667638c1574a09` 일치 |
| 5 | 메모리 | **미측정** |
| 6 | 폴백 경로 오탐 | **측정됨** — curl로 일반 HTML 8개 페이지: 0건. 브라우저 실측: 1건(`clients2.google.com` anti-XSSI). curl은 서브리소스를 받지 않아 재현 조건이 다르다 |

### 부수 — `mime_type` 오염 수정 확인

`responseheaders` 시점에 원본 `Content-Type`을 스냅샷해서 `flow.metadata`에 보관하고, 403 교체
후 `_emit()`이 그 값을 쓰도록 고쳤다. `BLOCK=True`로 검증: 원본이 `application/x-test-binary`였던
응답을 차단했을 때 이벤트에 `application/x-test-binary`가 정확히 기록됐다(수정 전에는
`text/plain`으로 오염됐을 자리).

### 결론

통과한 4건(다운로드 4종 전부 탐지, 서브리소스 지연 없음, HTTPS, `mime_type` 오염 수정)과
20건 중 순수 오탐 3건, 그리고 A안 채택 근거를 함께 보면: **`Sec-Fetch` 기반 맥락 규칙 전환으로
오탐이 139건에서 20건(순수 오탐 3건)까지 줄었지만, 완전한 "0건"은 이 재설계의 범위 밖이었다.**
Chrome 자동 업데이트처럼 사용자 행동과 무관하게 발생하는 정상 트래픽이 존재하는 한 이벤트 0건은
판별 로직 개선만으로는 닿지 않는 목표이며, 그 트래픽을 어떻게 다룰지(바이패스 여부와 사유 구분)는
상위 설계의 몫으로 남는다. 남은 오탐 3건은 각각 원인이 달라(제외 MIME 목록 누락, `octet-stream`
전제 붕괴, `Sec-Fetch` 없는 폴백 경로) 단일 규칙 수정으로는 닫히지 않는다.

## 참고

- `.mitmproxy/`는 CA 개인키를 포함하므로 `.gitignore` 처리되어 있다. 커밋하지 말 것.
- `docker-compose.yml`의 `tty: true`는 mitmdump가 stdout을 버퍼링하지 않고 바로 `docker compose logs`에 흘리도록 하기 위한 설정이다.
- addon은 `async def response` + `await asyncio.sleep()`을 쓴다. `time.sleep()` 같은 동기 블로킹 호출을 훅 안에 넣으면 이 프록시를 거치는 모든 트래픽이 직렬화된다 — 실제 서비스에 이 패턴을 적용할 때 반드시 유의할 것.
