<#
.SYNOPSIS
    Share the Factory Follow-up Dashboard on the internet with a Cloudflare Quick Tunnel.

.DESCRIPTION
    Starts the Django dev server and a Cloudflare Quick Tunnel, then prints the
    public URL that anybody with the link can open.

    A Quick Tunnel needs no Cloudflare account, no domain and no credit card.
    The only trade-off is that the URL is random and only lives as long as the
    tunnel process runs.

    The public host name is not known before the tunnel starts, so the tunnel
    comes up first and Django is started afterwards with that exact host name in
    DJANGO_ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS.  Without that the browser
    would reject the POST of the login form and of the data-entry forms.

.PARAMETER Port
    Local port for the Django dev server (default 8000).

.PARAMETER Stop
    Stop a share that is still running.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1
    powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1 -Stop
#>
param(
    [int]$Port = 8000,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StateFile = Join-Path $env:TEMP "factory-dashboard-share-$Port.json"

# ---------------------------------------------------------------- stop mode
if ($Stop) {
    if (-not (Test-Path $StateFile)) {
        Write-Host "Nothing to stop (no $StateFile)." -ForegroundColor Yellow
        exit 0
    }
    $state = Get-Content $StateFile -Raw | ConvertFrom-Json
    foreach ($id in @($state.WebPid, $state.TunnelPid)) {
        if ($id) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
    @{ Stopped = $true; StoppedAt = (Get-Date).ToString("s") } |
        ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
    Write-Host "Stopped. The public link is dead." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- start mode
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared is not installed." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install Cloudflare.cloudflared" -ForegroundColor Yellow
    exit 1
}

Set-Location $ProjectRoot

if (Test-Path $StateFile) {
    $previous = Get-Content $StateFile -Raw | ConvertFrom-Json
    $stillRunning = $false
    if (-not $previous.Stopped -and $previous.WebPid) {
        $stillRunning = [bool](Get-Process -Id $previous.WebPid -ErrorAction SilentlyContinue)
    }
    if ($stillRunning) {
        Write-Host "A share on port $Port is already running ($($previous.Url))." -ForegroundColor Yellow
        Write-Host "Stop it first:  powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1 -Stop" -ForegroundColor Yellow
        exit 1
    }
}

# --- 1. the tunnel first: it is what tells us the public host name --------
$tunnelLog = Join-Path $env:TEMP "cloudflared-$Port.log"
$tunnelErr = Join-Path $env:TEMP "cloudflared-$Port.err"

$tunnel = Start-Process -FilePath "cloudflared" `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate" `
    -RedirectStandardOutput $tunnelLog -RedirectStandardError $tunnelErr `
    -PassThru -WindowStyle Hidden

$publicUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    foreach ($file in @($tunnelLog, $tunnelErr)) {
        if (-not (Test-Path $file)) { continue }
        $hit = Select-String -Path $file -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
               Select-Object -First 1
        if ($hit) {
            $publicUrl = $hit.Matches[0].Value
            break
        }
    }
    if ($publicUrl) { break }
}

if (-not $publicUrl) {
    Write-Host "The tunnel did not report a URL - see $tunnelLog" -ForegroundColor Red
    Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

$hostName = ([uri]$publicUrl).Host

# --- 2. Django, now that we know the host name it will be reached on ------
$env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost,$hostName"
$env:CSRF_TRUSTED_ORIGINS = "https://$hostName"
$env:DJANGO_DEBUG = "True"

$web = Start-Process -FilePath "python" `
    -ArgumentList "manage.py", "runserver", "127.0.0.1:$Port", "--noreload" `
    -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 3

@{ WebPid = $web.Id; TunnelPid = $tunnel.Id; Url = $publicUrl; Port = $Port } |
    ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8

Write-Host ""
Write-Host "  Dashboard is live at:" -ForegroundColor Green
Write-Host "    $publicUrl" -ForegroundColor Green
Write-Host ""
Write-Host "  Sign in with:" -ForegroundColor Green
Write-Host "    admin / factory123   (full access)"
Write-Host "    supervisor / factory123   (LINE-A, morning shift)"
Write-Host "    operator / factory123   (data entry only)"
Write-Host ""
Write-Host "  The link works for anybody who has it and dies when you stop it."
Write-Host "  Stop the share with:" -ForegroundColor Yellow
Write-Host "    powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1 -Stop" -ForegroundColor Yellow
Write-Host ""
