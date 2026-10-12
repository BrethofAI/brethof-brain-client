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
#
# -Rotate (what rotate-key.ps1 runs) replaces it in one step: the new key goes
# into this stack's key file and your agents' config, the old one stops
# working at once, and the running memory and agents pick up the new one by
# themselves -- no restart.
param([switch]$Rotate)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$KeyDir  = if ($env:BRAIN_KEY_DIR)  { $env:BRAIN_KEY_DIR }  else { Join-Path $PSScriptRoot 'keys' }
$KeyFile = Join-Path $KeyDir 'v2keys'
$Tenant  = if ($env:BRAIN_TENANT)   { $env:BRAIN_TENANT }   else { 'memory' }
$Port    = if ($env:BRAIN_API_PORT) { $env:BRAIN_API_PORT } else { '8610' }

if ($Rotate) {
    if (-not (Test-Path $KeyFile) -or -not (Get-Content $KeyFile -TotalCount 1)) {
        Write-Error "no key to rotate in $KeyFile -- run install.ps1 first"
    }
    # the memory's name stays: it is the database the key opens
    $Tenant = ((Get-Content $KeyFile -TotalCount 1) -split ':')[1]
} elseif (Test-Path $KeyFile) {
    Write-Error ("$KeyFile already exists. To replace the key, run rotate-key.ps1 -- " +
                 "it updates your agents' config in the same step.")
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
# written beside and moved over: the running memory sees a whole file or the
# old one, never half of one (it re-reads the file when it changes)
Set-Content -NoNewline -Path "$KeyFile.tmp" -Value "${Hash}:${Tenant}:customer`n"
Move-Item -Force "$KeyFile.tmp" $KeyFile
if ($Rotate) { Write-Output 'rotated: the old key stopped working just now' }

# THE KEY GOES STRAIGHT INTO THE CLIENT'S CONFIG (2026-10-04): an agent runs
# this install, and a key printed here lands in its chat -- so it is written to
# %USERPROFILE%\.brethof-brain\config.json (pointed at this memory; the
# profile's own permissions keep it yours) and never shown. BRAIN_SHOW_KEY=1
# shows it as well, for wiring another tool by hand.
$Saved = ''
if ($env:BRAIN_SHOW_KEY -ne '1') {
    try {
        $home2 = if ($env:BRETHOF_BRAIN_HOME) { $env:BRETHOF_BRAIN_HOME } else { Join-Path $env:USERPROFILE '.brethof-brain' }
        New-Item -ItemType Directory -Force -Path $home2 | Out-Null
        $cfgPath = Join-Path $home2 'config.json'
        $conf = @{}
        if (Test-Path $cfgPath) {
            $old = Get-Content -Raw $cfgPath | ConvertFrom-Json
            foreach ($prop in $old.PSObject.Properties) { $conf[$prop.Name] = $prop.Value }
        }
        $conf['api_key'] = $Key
        $conf['endpoint'] = "http://127.0.0.1:$Port"
        if (-not $conf.ContainsKey('default_project')) { $conf['default_project'] = 'global' }
        $tmp = "$cfgPath.tmp"
        [IO.File]::WriteAllText($tmp, ($conf | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
        Move-Item -Force $tmp $cfgPath
        $Saved = $cfgPath
    } catch { $Saved = '' }
}
if ($Saved) {
    Write-Output ''
    Write-Output "  Your memory key is saved for your agents: $Saved"
    Write-Output '  (it is not shown here). The brethof-brain hooks and plugins read it from there.'
    if ($Rotate) {
        Write-Output '  They use the new key on their next call, no restart. A tool you wired by'
        Write-Output '  hand with the old key needs the new one: set BRAIN_SHOW_KEY=1 and rotate again.'
    }
    Write-Output ''
    Write-Output "  Stored on the memory side: $KeyFile (the hash only)"
    Write-Output ''
} else {
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
}
