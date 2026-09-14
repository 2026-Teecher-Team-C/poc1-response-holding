<#
Windows 네이티브(Docker 없이) mitmproxy 실행 환경을 준비합니다.
관리자 권한 불필요. Python 3.9~3.12 중 하나가 설치되어 있어야 합니다 (3.13+는 mitmproxy 호환성 미검증).

사용법:
    cd poc1-response-holding
    .\windows\setup-venv.ps1
    .\windows\run-mitmdump.ps1
#>

$ErrorActionPreference = "Stop"

$pyVersion = (python --version) 2>&1
Write-Host "감지된 Python: $pyVersion"
if ($pyVersion -match "3\.1[3-9]" -or $pyVersion -match "3\.[2-9][0-9]") {
    Write-Warning "Python 3.13 이상은 mitmproxy 호환성이 검증되지 않았습니다. 3.9~3.12 사용을 권장합니다."
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

Write-Host "`n설치 완료. 다음으로 .\windows\run-mitmdump.ps1 을 실행하세요."
