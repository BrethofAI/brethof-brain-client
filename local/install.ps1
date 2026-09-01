# brethof-brain local install for Windows (Docker Desktop) - the same six
# steps as install.sh: runtime check, model download+verify, images
# download+verify, load, key mint, compose up. Rerunning is safe; a newer
# published version is exactly how you upgrade.
#
# ASCII ONLY in this file: Windows PowerShell 5.1 reads BOM-less files as
# ANSI and a UTF-8 dash breaks the parse.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$DL = if ($env:BRAIN_DL_URL) { $env:BRAIN_DL_URL } else { "https://downloads.brethof.ai/brain" }
$ModelFile = "embeddinggemma-300m-fp32.tar.gz"

function Say($m)  { Write-Host "`n== $m" }
function Fail($m) { Write-Host "INSTALL FAILED: $m" -ForegroundColor Red; exit 1 }

function Get-Verified($url, $out) {
    curl.exe -fL -C - -o $out $url
    if ($LASTEXITCODE -ne 0) { Fail "download $url" }
    curl.exe -fsSL -o "$out.sha256" "$url.sha256"
    if ($LASTEXITCODE -ne 0) { Fail "checksum download $url.sha256" }
    $want = (Get-Content "$out.sha256").Split(" ")[0].Trim()
    $got  = (Get-FileHash $out -Algorithm SHA256).Hash.ToLower()
    if ($want -ne $got) { Fail "checksum MISMATCH for $out - delete it and rerun" }
}

Say "runtime check"
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop with compose is required" }

Say "embedding model (local semantic search - text never leaves this machine)"
if (Test-Path "model/embeddinggemma-300m-onnx") {
    Write-Host "already present - skipped"
} else {
    New-Item -ItemType Directory -Force -Path model | Out-Null
    Get-Verified "$DL/models/$ModelFile" "model/$ModelFile"
    tar.exe xzf "model/$ModelFile" -C model
    if ($LASTEXITCODE -ne 0) { Fail "model extract" }
    Remove-Item "model/$ModelFile", "model/$ModelFile.sha256"
    Write-Host "model verified and extracted"
}

Say "container images"
$Version = if ($env:BRAIN_VERSION) { $env:BRAIN_VERSION } else { (curl.exe -fsSL "$DL/latest.txt").Trim() }
if (-not $Version) { Fail "could not resolve the current version" }
Write-Host "version: $Version"
$Bundle = "brain-images-$Version.tar.gz"
docker image inspect "downloads.brethof.ai/brain-api:$Version" *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "images for $Version already loaded - skipped"
} else {
    Get-Verified "$DL/images/$Bundle" $Bundle
    docker load -i $Bundle
    if ($LASTEXITCODE -ne 0) { Fail "image load" }
    Remove-Item $Bundle, "$Bundle.sha256"
    Write-Host "images loaded"
}

Say "your .env"
if (-not (Test-Path ".env")) { Copy-Item env.example .env }
$envText = Get-Content .env -Raw
if ($envText -match "(?m)^BRAIN_VERSION=") {
    $envText = $envText -replace "(?m)^BRAIN_VERSION=.*", "BRAIN_VERSION=$Version"
} else {
    $envText += "`nBRAIN_VERSION=$Version`n"
}
if ($envText -notmatch "(?m)^BRAIN_DB_PASSWORD=.+") {
    $bytes = New-Object byte[] 16
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
    $envText = $envText -replace "(?m)^BRAIN_DB_PASSWORD=.*", "BRAIN_DB_PASSWORD=$pw"
    if ($envText -notmatch "(?m)^BRAIN_DB_PASSWORD=.+") { $envText += "`nBRAIN_DB_PASSWORD=$pw`n" }
    Write-Host "BRAIN_DB_PASSWORD generated"
}
Set-Content .env $envText -NoNewline
if ($envText -notmatch "(?m)^(BRAIN_PASSPHRASE|BRAIN_PASSPHRASE_FILE)=.+") {
    Fail "set BRAIN_PASSPHRASE in .env first - it encrypts your memory on disk and only you hold it. Then rerun this script."
}

Say "memory key"
if (Test-Path "keys/v2keys") {
    Write-Host "key already minted - skipped"
} else {
    powershell -ExecutionPolicy Bypass -File mint-key.ps1
    if ($LASTEXITCODE -ne 0) { Fail "mint-key.ps1" }
}

Say "starting the stack"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Fail "compose up" }
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8610/v1/health | Out-Null
        $healthy = $true; break
    } catch { Start-Sleep -Seconds 5 }
}
if (-not $healthy) { docker logs brain-api 2>&1 | Select-Object -Last 20; Fail "stack never became healthy" }

Say "DONE - your memory answers on http://127.0.0.1:8610/v1/mcp"
Write-Host "   (add BRAIN_HUB_KEY from your account panel to .env to turn on"
Write-Host "    learning - recall and archiving work without it)"
