$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ExportScript = Join-Path $ProjectRoot "scripts\export_subscriptions_meta.py"
$GeneratedFile = Join-Path $ProjectRoot "deploy\vpn-subscription\subscriptions_meta.generated.json"
$EnvFile = Join-Path $ProjectRoot ".env"

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

function Read-DotEnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) {
        return $null
    }

    foreach ($RawLine in Get-Content $EnvFile) {
        $Line = $RawLine.Trim()

        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            continue
        }

        $Key, $Value = $Line.Split("=", 2)

        if ($Key.Trim() -eq $Name) {
            return $Value.Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

function Resolve-RemoteTarget {
    if ($env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET) {
        return $env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET
    }

    $Configured = Read-DotEnvValue "SUBSCRIPTION_META_REMOTE_TARGET"

    if ($Configured) {
        return $Configured
    }

    throw "Set SUBSCRIPTION_META_REMOTE_TARGET in .env or VPN_SUBSCRIPTIONS_META_REMOTE_TARGET in PowerShell."
}

function Resolve-SshKey {
    if ($env:VPN_SUBSCRIPTIONS_META_SSH_KEY) {
        return $env:VPN_SUBSCRIPTIONS_META_SSH_KEY
    }

    return Read-DotEnvValue "SUBSCRIPTION_META_SSH_KEY"
}

function Parse-RemoteTarget([string]$Target) {
    $Match = [regex]::Match(
        $Target,
        '^(?<host>[A-Za-z0-9_.@-]+):(?<path>/[A-Za-z0-9_./-]+)$'
    )

    if (-not $Match.Success) {
        throw "Remote target must look like user@host:/absolute/path without spaces: $Target"
    }

    $RemoteHost = $Match.Groups["host"].Value
    $RemotePath = $Match.Groups["path"].Value
    $LastSlash = $RemotePath.LastIndexOf("/")

    if ($LastSlash -le 0 -or $LastSlash -eq ($RemotePath.Length - 1)) {
        throw "Remote target must include a file name: $Target"
    }

    return @{
        Host = $RemoteHost
        Path = $RemotePath
        Directory = $RemotePath.Substring(0, $LastSlash)
        FileName = $RemotePath.Substring($LastSlash + 1)
    }
}

$Python = Resolve-Python
$RemoteTarget = Resolve-RemoteTarget
$SshKey = Resolve-SshKey
$Remote = Parse-RemoteTarget $RemoteTarget

$UniqueSuffix = [guid]::NewGuid().ToString("N")
$RemoteTempPath = "$($Remote.Directory)/.$($Remote.FileName).$UniqueSuffix.tmp"
$RemoteTempTarget = "$($Remote.Host):$RemoteTempPath"

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

Write-Host "Validating generated JSON..."
try {
    Get-Content $GeneratedFile -Raw | ConvertFrom-Json | Out-Null
}
catch {
    throw "Generated metadata is not valid JSON: $GeneratedFile"
}

$CommonSshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new"
)

if ($SshKey) {
    $CommonSshArgs += @("-i", $SshKey)
}

try {
    Write-Host "Uploading metadata to temporary remote file..."
    & scp @CommonSshArgs $GeneratedFile $RemoteTempTarget

    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed with exit code $LASTEXITCODE"
    }

    Write-Host "Validating and atomically publishing metadata..."
    $PublishCommand = @(
        "set -eu"
        "python3 -m json.tool '$RemoteTempPath' >/dev/null"
        "chmod 0660 '$RemoteTempPath'"
        "mv -f '$RemoteTempPath' '$($Remote.Path)'"
    ) -join "; "

    & ssh @CommonSshArgs $Remote.Host $PublishCommand

    if ($LASTEXITCODE -ne 0) {
        throw "Remote atomic publish failed with exit code $LASTEXITCODE"
    }
}
catch {
    $OriginalError = $_

    $CleanupCommand = "rm -f '$RemoteTempPath'"
    & ssh @CommonSshArgs $Remote.Host $CleanupCommand 2>$null | Out-Null

    throw $OriginalError
}

Write-Host "Done."
