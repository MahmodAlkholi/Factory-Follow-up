<#
.SYNOPSIS
    Point the README at the currently running demo.

.DESCRIPTION
    A Cloudflare Quick Tunnel gets a new random address every time the share
    is restarted, so the link in the README goes stale.  This script rewrites
    the "Live demo" block in README.md with the address that is live now.

    It only edits the file - it never commits and never pushes, because the
    repository is public and a surprise push is not welcome.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/update_readme_url.ps1 -Url https://abc.trycloudflare.com
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,

    [string]$Readme = "",
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Readme) {
    $Readme = Join-Path $ProjectRoot "README.md"
}

if (-not (Test-Path $Readme)) {
    Write-Host "No README at $Readme" -ForegroundColor Red
    exit 1
}

$Url = $Url.TrimEnd('/')
if ($Url -notmatch '^https://') {
    Write-Host "The URL must start with https://" -ForegroundColor Red
    exit 1
}

$content = [System.IO.File]::ReadAllText($Readme)
$pattern = '(?m)^> \*\*Live demo:\*\* <https://[^\s>]+>$'

if ($content -match $pattern) {
    $updated = [regex]::Replace($content, $pattern, "> **Live demo:** <$Url>")
} elseif ($content -match '(?m)^> \*\*Live demo:\*\*.*$') {
    $updated = [regex]::Replace(
        $content,
        '(?m)^> \*\*Live demo:\*\*.*$',
        "> **Live demo:** <$Url>"
    )
} else {
    # No block yet - insert it right after the intro paragraph.
    $block = @(
        "> **Live demo:** <$Url>",
        "> Sign in with ``admin`` / ``factory123``.",
        "> This is a temporary Cloudflare Quick Tunnel (see section 12.6) - the",
        "> address changes every time the demo is restarted, so it may be dead by",
        "> the time you read this.",
        ""
    ) -join "`n"
    $updated = [regex]::Replace($content, '(?m)^(\r?\n){2,}', "`n`n$block`n", 1)
}

if ($updated -eq $content) {
    Write-Host "README already points at $Url" -ForegroundColor Green
    exit 0
}

if ($Check) {
    Write-Host "README would be updated to $Url" -ForegroundColor Yellow
    exit 1
}

# UTF-8 without a BOM, and the line endings of the file are kept as they are.
[System.IO.File]::WriteAllText($Readme, $updated, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "README now points at $Url" -ForegroundColor Green
Write-Host "Review it, then: git add README.md && git commit -m `"...`" && git push" -ForegroundColor Yellow
