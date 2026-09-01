# Create the key your agent uses to reach YOUR memory -- Windows twin of
# mint-key.sh (same contract, native PowerShell: Docker Desktop customers
# should not need a bash to mint a key). Run once, before the first
# `docker compose up`:
#
#     powershell -ExecutionPolicy Bypass -File mint-key.ps1
#
# The key is shown ONCE and never stored: this stack keeps only its SHA-256
# hash, so nobody -- including us -- can read it back out of your files. Lose
# it and you mint another; there is no recovery and none is needed.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$KeyDir  = if ($env:BRAIN_KEY_DIR)  { $env:BRAIN_KEY_DIR }  else { Join-Path $PSScriptRoot 'keys' }
$KeyFile = Join-Path $KeyDir 'v2keys'
$Tenant  = if ($env:BRAIN_TENANT)   { $env:BRAIN_TENANT }   else { 'memory' }
$Port    = if ($env:BRAIN_API_PORT) { $env:BRAIN_API_PORT } else { '8610' }

if (Test-Path $KeyFile) {
    Write-Error ("$KeyFile already exists. Delete it to mint a new key -- and " +
                 "update your agent's config when you do, because the old one " +
                 "stops working.")
}
if ($Tenant -notmatch '^[a-z0-9_]{3,40}$') {
    Write-Error 'BRAIN_TENANT must be 3-40 chars of a-z, 0-9, _'
}

$bytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$Key = 'bmv2_' + (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')

$sha = [System.Security.Cryptography.SHA256]::Create()
$Hash = (($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($Key)) |
          ForEach-Object { $_.ToString('x2') }) -join '')

New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
# ':customer' = the tool tier. The product speaks the brain vocabulary
# (search_brain, save_general, ...) -- the same names every guide teaches.
# The file holds a hash and a name, never the key -- see mint-key.sh for why
# its permissions are deliberately ordinary.
Set-Content -NoNewline -Path $KeyFile -Value "${Hash}:${Tenant}:customer`n"

Write-Output ''
Write-Output '  Your memory key -- copy it now, it is not shown again:'
Write-Output ''
Write-Output "    $Key"
Write-Output ''
Write-Output '  Point your agent at this stack with:'
Write-Output ''
Write-Output '    "brain": {'
Write-Output '      "type": "http",'
Write-Output "      `"url`": `"http://127.0.0.1:$Port/v1/mcp`","
Write-Output "      `"headers`": { `"Authorization`": `"Bearer $Key`" }"
Write-Output '    }'
Write-Output ''
Write-Output "  Stored: $KeyFile (the hash only)"
Write-Output ''
