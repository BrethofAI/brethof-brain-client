# Connect this memory to your brethof.ai account, so it learns: the hub key.
# Windows twin of login.sh:
#
#     powershell -ExecutionPolicy Bypass -File login.ps1
#
# It prints a link and a short code. Open the link while signed in to
# brethof.ai, check the code is the one shown here, and press Approve. The
# hub key then comes straight back to this script and is written into .env --
# it is never printed, so an agent running the install never sees it.
#
# One hub key per memory: a new one replaces the old. Running this again is
# how the hub key is rotated, and a second machine still holding the old key
# stops learning until it is connected again (recall and the archive keep
# working there -- they never need the hub).
#
# ASCII ONLY in this file (Windows PowerShell 5.1 reads BOM-less files as ANSI).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Control = if ($env:BRETHOF_BRAIN_CONTROL_URL) { $env:BRETHOF_BRAIN_CONTROL_URL.TrimEnd('/') } else { 'https://api.brethof.ai' }

# One POST that returns @(status, body) for 2xx AND 4xx alike: the RFC 8628
# answers (authorization_pending, slow_down, ...) arrive as 400s, which
# Windows PowerShell 5.1 throws instead of returning.
function Post-Json($path, $body) {
    $json = $body | ConvertTo-Json -Compress
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Method Post -ContentType 'application/json' `
                -Body $json -TimeoutSec 30 -Uri ($Control + $path)
        return @([int]$r.StatusCode, ($r.Content | ConvertFrom-Json))
    } catch {
        $resp = $_.Exception.Response
        if ($null -eq $resp) { return @(0, [pscustomobject]@{ error_description = $_.Exception.Message }) }
        $text = ''
        try {
            $reader = New-Object IO.StreamReader($resp.GetResponseStream())
            $text = $reader.ReadToEnd()
        } catch { $text = '' }
        $obj = $null
        try { $obj = $text | ConvertFrom-Json } catch { $obj = [pscustomobject]@{} }
        return @([int]$resp.StatusCode, $obj)
    }
}

if (-not (Test-Path '.env')) { Copy-Item env.example .env }

$name = ("brethof-brain local install on " + $env:COMPUTERNAME)
if ($name.Length -gt 80) { $name = $name.Substring(0, 80) }
$res = Post-Json '/v1/device/code' @{ product = 'brain-local'; client_name = $name }
$st = $res[0]; $code = $res[1]
if ($st -ne 200 -or -not $code.device_code) {
    $why = if ($code.error_description) { $code.error_description } elseif ($code.error) { $code.error } else { 'no answer' }
    Write-Host "login failed: could not start the sign-in ($st`: $why)" -ForegroundColor Red
    exit 1
}
$link = if ($code.verification_uri_complete) { $code.verification_uri_complete } else { $code.verification_uri }
Write-Host 'To connect this memory to your brethof.ai account, open this page while signed in:'
Write-Host "  $link"
Write-Host "check that it shows the code  $($code.user_code)  and press Approve."
if ($env:BRAIN_NO_BROWSER -ne '1') {
    try { Start-Process $link | Out-Null } catch { }
}

$interval = [Math]::Max(1, [int]$code.interval)
$deadline = (Get-Date).AddSeconds([int]$code.expires_in)
$tok = $null
while ($true) {
    if ((Get-Date) -gt $deadline) {
        Write-Host 'login failed: the code expired before it was approved - run login.ps1 again' -ForegroundColor Red
        exit 1
    }
    Start-Sleep -Seconds $interval
    $res = Post-Json '/v1/device/token' @{ device_code = $code.device_code }
    $st = $res[0]; $tok = $res[1]
    if ($st -eq 200 -and $tok.hub_key) { break }
    if ($tok.error -eq 'authorization_pending') { continue }
    if ($tok.error -eq 'slow_down') { $interval += 5; continue }
    $why = if ($tok.error_description) { $tok.error_description } elseif ($tok.error) { $tok.error } else { "HTTP $st" }
    Write-Host "login failed: $why" -ForegroundColor Red
    exit 1
}

# write .env: replace or add the one line; the key goes only into the file
$lines = New-Object System.Collections.Generic.List[string]
$done = $false
foreach ($ln in (Get-Content .env)) {
    if ($ln -like 'BRAIN_HUB_KEY=*') {
        if (-not $done) { $lines.Add('BRAIN_HUB_KEY=' + $tok.hub_key); $done = $true }
        continue
    }
    $lines.Add($ln)
}
if (-not $done) { $lines.Add('BRAIN_HUB_KEY=' + $tok.hub_key) }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env.tmp'), (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
Move-Item -Force (Join-Path $PSScriptRoot '.env.tmp') (Join-Path $PSScriptRoot '.env')
$msg = 'connected: the hub key is in .env (not shown here)'
if ($tok.replaced) { $msg += ' - it replaces the previous one; another machine still using the old key learns again once it is connected' }
Write-Host $msg

# a running memory reads .env only when its container is created
$prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
try {
    # this install's own compose project, never a container name another
    # stack could share; the key is saved already, so a failure is a note
    if (Test-Path (Join-Path $PSScriptRoot 'compose.yml')) {
        $up = & docker compose ps -q brain-api 2>$null
        if ($up) {
            & docker compose up -d brain-api *> $null
            if ($LASTEXITCODE -eq 0) { Write-Host 'your running memory now uses it' }
            else { Write-Host 'restart your memory so it uses the new key: docker compose up -d' }
        }
    }
} finally { $ErrorActionPreference = $prev }
exit 0
