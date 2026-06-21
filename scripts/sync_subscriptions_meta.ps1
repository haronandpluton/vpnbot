$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\User\PycharmProjects\pythonProject\.venv\Scripts\python.exe"
$ExportScript = Join-Path $ProjectRoot "scripts\export_subscriptions_meta.py"
$GeneratedFile = Join-Path $ProjectRoot "deploy\vpn-subscription\subscriptions_meta.generated.json"
$RemoteTarget = "root@151.243.212.64:/opt/vpn-subscription/subscriptions_meta.json"

Write-Host "Exporting subscription metadata..."
& $Python $ExportScript

Write-Host "Uploading metadata to VPS..."
scp $GeneratedFile $RemoteTarget

Write-Host "Done."