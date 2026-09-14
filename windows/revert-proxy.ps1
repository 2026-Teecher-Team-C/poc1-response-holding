<#
setup-proxy.ps1로 설정한 프록시와 CA 인증서 신뢰를 원복합니다.
mitmproxy CA를 신뢰 상태로 남겨두면 그 CA로 서명된 모든 HTTPS를 브라우저가 믿게 되므로
테스트가 끝나면 반드시 실행하세요.

반드시 관리자 권한으로 실행하세요.
#>

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "관리자 권한으로 실행해주세요. PowerShell을 '관리자 권한으로 실행'으로 열고 다시 시도하세요."
    exit 1
}

Write-Host "1) 사용자 프록시를 끕니다..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 0

Write-Host "2) mitmproxy CA 인증서를 '신뢰할 수 있는 루트 인증 기관'에서 삭제합니다..."
# certutil -delstore 는 Subject(CN)에 포함된 문자열로도 매치된다 — mitmproxy CA는 CN에 "mitmproxy"를 포함.
certutil -delstore "ROOT" "mitmproxy" 2>$null | Out-Null

Write-Host "`n완료. 브라우저를 재시작해서 프록시가 꺼졌는지 확인하세요."
