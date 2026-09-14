<#
Windows 시스템(사용자) 프록시를 mitmdump(127.0.0.1:8080)로 설정하고,
mitmproxy CA 인증서를 "신뢰할 수 있는 루트 인증 기관" 저장소에 등록합니다.

반드시 관리자 권한으로 실행하세요 (PowerShell을 "관리자 권한으로 실행"으로 열기).
실행 전에 run-mitmdump.ps1 을 최소 한 번 띄워서 CA 인증서 파일이 생성되어 있어야 합니다
(기본 경로: %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer).

테스트가 끝나면 revert-proxy.ps1 을 반드시 실행해서 원복하세요.
HTTP만 테스트할 거라면 인증서 등록 없이 프록시 설정만 해도 됩니다.
#>

param(
    [string]$ProxyHost = "127.0.0.1",
    [int]$ProxyPort = 8080,
    [string]$CertPath = "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer",
    [switch]$SkipCert
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "관리자 권한으로 실행해주세요. PowerShell을 '관리자 권한으로 실행'으로 열고 다시 시도하세요."
    exit 1
}

if (-not $SkipCert) {
    if (-not (Test-Path $CertPath)) {
        Write-Warning "인증서 파일을 찾을 수 없습니다: $CertPath"
        Write-Warning "run-mitmdump.ps1 을 먼저 실행해서 CA 인증서를 생성하거나, -SkipCert 옵션으로 HTTP만 테스트하세요."
        exit 1
    }
    Write-Host "1) mitmproxy CA 인증서를 '신뢰할 수 있는 루트 인증 기관'에 등록합니다: $CertPath"
    certutil -addstore -f "ROOT" "$CertPath" | Out-Null
} else {
    Write-Host "1) -SkipCert 지정됨 — 인증서 등록 생략 (HTTPS 인터셉션은 동작하지 않음)"
}

Write-Host "2) 사용자 프록시를 ${ProxyHost}:${ProxyPort} 로 설정합니다..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 1
Set-ItemProperty -Path $regPath -Name ProxyServer -Value "${ProxyHost}:${ProxyPort}"

Write-Host "`n완료. 브라우저를 재시작한 뒤 테스트하세요."
Write-Host "테스트가 끝나면 반드시 .\windows\revert-proxy.ps1 을 실행해서 원복하세요."
