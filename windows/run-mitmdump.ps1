<#
setup-venv.ps1로 만든 가상환경에서 mitmdump(addon 포함)를 실행합니다.
이 창은 mitmdump가 실행되는 동안 열어둔 채로 두세요 (Ctrl+C로 종료).
#>

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "가상환경이 없습니다. 먼저 .\windows\setup-venv.ps1 을 실행하세요."
    exit 1
}

& .\.venv\Scripts\Activate.ps1
mitmdump -s addons\hold_response.py -p 8080
