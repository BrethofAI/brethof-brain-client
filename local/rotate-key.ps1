# Replace your memory key in one step (a leaked key, a machine you gave away)
# -- Windows twin of rotate-key.sh:
#
#     powershell -ExecutionPolicy Bypass -File rotate-key.ps1
#
# A new key goes into this stack's key file and into your agents' config
# (%USERPROFILE%\.brethof-brain\config.json); the old key stops working at
# once. The running memory and your agents pick the new one up by themselves
# -- nothing restarts, and the key is never printed. BRAIN_SHOW_KEY=1 shows
# it, for a tool you wired by hand.
#
# This is the memory key, the one your agents use. The hub key (learning) is
# replaced by login.ps1.
#
# ASCII ONLY in this file (Windows PowerShell 5.1 reads BOM-less files as ANSI).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'mint-key.ps1') -Rotate
exit $LASTEXITCODE
