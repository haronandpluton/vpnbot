$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExportScript = Join-Path $ProjectRoot "scripts\export_subscriptions_meta.py"
$GeneratedFile = Join-Path $ProjectRoot "deploy\vpn-subscription\subscriptions_meta.generated.json"

function Resolve-Python {
    if ($env:PYTHON_EXE) {
        return $env:PYTHON_EXE
    }

    $LocalVenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

    if (Test-Path $LocalVenvPython) {
        return $LocalVenvPython
    }

    return "python"
}

function Resolve-RemoteTarget {
    if ($env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET) {
        return $env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET
    }

    return "root@151.243.212.64:/opt/vpn-subscription/subscriptions_meta.json"
}

$Python = Resolve-Python
$RemoteTarget = Resolve-RemoteTarget

Write-Host "Project root: $ProjectRoot"
Write-Host "Python: $Python"
Write-Host "Export script: $ExportScript"
Write-Host "Generated file: $GeneratedFile"
Write-Host "Remote target: $RemoteTarget"

if (-not (Test-Path $ExportScript)) {
    throw "Export script not found: $ExportScript"
}

Write-Host "Exporting subscription metadata..."
& $Python $ExportScript

if ($LASTEXITCODE -ne 0) {
    throw "Export failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $GeneratedFile)) {
    throw "Generated metadata file not found: $GeneratedFile"
}

Write-Host "Uploading metadata to VPS..."
scp $GeneratedFile $RemoteTarget

if ($LASTEXITCODE -ne 0) {
    throw "SCP upload failed with exit code $LASTEXITCODE"
}

Write-Host "Done."