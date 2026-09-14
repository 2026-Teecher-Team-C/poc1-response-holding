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
| `addons/hold_response.py` | 응답 보류 addon. `time.sleep(3)` 후 `BLOCK` 값에 따라 403 차단 또는 통과 |
| `testdata/sample.txt` | 테스트용 샘플 다운로드 파일 (13KB) |
| `requirements.txt` | mitmproxy 버전 고정 (`12.2.3` — Docker 검증에 쓰인 것과 동일 버전) |
| `windows/` | Docker 없이 Windows에 네이티브로 설치/실행/원복하는 PowerShell 스크립트 모음 |

### addon 동작

```python
BLOCK = False  # 데모용 토글 — 추후 판정 로직 결과로 교체

def response(flow: http.HTTPFlow):
    time.sleep(3)
    if BLOCK:
        flow.response = http.Response.make(
            403, b"Blocked by malware detection platform", {"Content-Type": "text/plain"}
        )
```

mitmproxy의 `response` 훅은 **업스트림 응답을 다 받은 뒤, 클라이언트로 내려보내기 전에** 호출된다.
따라서 이 훅 안에서 블로킹하면 클라이언트는 헤더조차 받지 못한 채 대기하고, 훅이 끝난 시점에 통과 또는 교체된 응답을 받는다.

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
| 다운로드 요청이 3초 지연됨 | 통과 | 0.0009s → 3.014s / 3.017s |
| `BLOCK=False`일 때 파일이 정상 저장됨 | 통과 | 200, 13248바이트, SHA-256 원본과 동일 |
| `BLOCK=True`일 때 403으로 차단됨 | 통과 | 403 `Blocked by malware detection platform`, 본문 37바이트 |
| 재현 가능하도록 리포에 기록/커밋 | 통과 | 이 리포 (`docker compose build && docker compose up -d` + 위 curl 절차) |

**결론: 응답 보류 전제는 유효하다.** 헤더 전송 전에 응답을 붙잡아둘 수 있고, 판정 결과에 따라 통과/차단 분기가 동작한다.

### 아직 검증되지 않은 것 (남은 수동 단계)

curl 기반 검증은 시스템 설정을 건드리지 않는 범위에서 수행했다. 아래는 **시스템 전역 설정 변경이 필요해 사용자가 직접 해야 하는** 항목이다.

- 실제 브라우저(Chrome 등)에서의 다운로드 동작 — 브라우저가 3초를 기다려주는지, 다운로드 UI가 어떻게 보이는지
- HTTPS 인터셉션 (CA 신뢰 등록 필요)
- 대용량 파일에서의 메모리 버퍼링 거동 (`flow.response.stream`)

## 수동 설정 가이드 (macOS) — 사용자가 직접 진행

> 아래 두 가지는 **시스템 전역 설정을 바꾸는 작업**이라 자동화하지 않았다. 직접 수행해야 한다.
> PoC 확인이 끝나면 **프록시 설정과 CA 신뢰를 반드시 원복**할 것. mitmproxy CA를 신뢰한 상태로 두면 그 CA로 서명된 모든 HTTPS를 브라우저가 믿게 된다.

### 1. CA 인증서를 키체인에 "항상 신뢰"로 등록

컨테이너가 처음 기동되면 바인드 마운트를 통해 호스트에 CA 파일이 생성된다:

```
./.mitmproxy/mitmproxy-ca-cert.pem
```

(이번 실행에서 실제로 생성됨을 확인했고, 호스트 사용자 소유로 만들어져 권한 조정이 필요 없었다.)

1. Finder에서 `.mitmproxy/mitmproxy-ca-cert.pem`을 더블클릭 → 키체인 접근이 열림
2. "시스템" 키체인에 추가 (관리자 암호 1회)
3. 키체인 접근에서 `mitmproxy` 인증서를 더블클릭 → **신뢰** 섹션 펼치기 → "이 인증서 사용 시" → **항상 신뢰**
4. 창을 닫고 암호 재입력

HTTP만 테스트한다면 이 단계는 건너뛸 수 있다.

### 2. macOS 시스템 네트워크 프록시 설정

시스템 설정 → 네트워크 → (사용 중인 인터페이스) → 세부사항… → 프록시:

- **웹 프록시(HTTP)** 켜기 → 서버 `localhost`, 포트 `8080`
- **보안 웹 프록시(HTTPS)** 켜기 → 서버 `localhost`, 포트 `8080`

컨테이너가 8080을 호스트에 매핑하므로 브라우저 입장에서는 `localhost:8080`으로 보인다.

### 3. 브라우저 다운로드 테스트

⚠️ Chrome은 QUIC(HTTP/3, UDP)으로 TCP 기반 프록시를 우회할 수 있다. 그러면 addon을 아예 타지 않아 "지연 없이 통과"로 보이는 **오탐**이 난다.

- 권장: QUIC을 지원하지 않는 로컬 서버로 테스트 (`python3 -m http.server 8000 --directory testdata` → `http://localhost:8000/sample.txt`)
- 또는 `chrome://flags/#enable-quic` 에서 QUIC 비활성화

`BLOCK=False`에서 3초 뒤 다운로드 시작 / `BLOCK=True`에서 403 표시 + 파일 미저장을 확인하면 브라우저 레벨 검증까지 완료된다.

### 4. 원복

테스트 후 시스템 프록시 설정을 끄고, 키체인에서 mitmproxy CA 인증서를 삭제할 것.

## 참고

- `.mitmproxy/`는 CA 개인키를 포함하므로 `.gitignore` 처리되어 있다. 커밋하지 말 것.
- `docker-compose.yml`의 `tty: true`는 mitmdump가 stdout을 버퍼링하지 않고 바로 `docker compose logs`에 흘리도록 하기 위한 설정이다.
