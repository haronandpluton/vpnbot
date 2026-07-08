from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/sync_subscriptions_meta.ps1")


def script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_sync_subscriptions_meta_script_does_not_hardcode_local_python_path():
    text = script_text()

    assert "C:\\Users\\User\\PycharmProjects\\pythonProject" not in text
    assert "$env:PYTHON_EXE" in text
    assert 'Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"' in text
    assert 'return "python"' in text


def test_sync_subscriptions_meta_script_reads_remote_target_from_env_or_dotenv():
    text = script_text()

    assert "$env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET" in text
    assert 'Read-DotEnvValue "SUBSCRIPTION_META_REMOTE_TARGET"' in text
    assert "151.243.212.64" not in text
    assert "Set SUBSCRIPTION_META_REMOTE_TARGET in .env" in text
    assert "$RemoteTarget = Resolve-RemoteTarget" in text


def test_sync_subscriptions_meta_script_supports_optional_ssh_key():
    text = script_text()

    assert "$env:VPN_SUBSCRIPTIONS_META_SSH_KEY" in text
    assert 'Read-DotEnvValue "SUBSCRIPTION_META_SSH_KEY"' in text
    assert '$CommonSshArgs += @("-i", $SshKey)' in text


def test_sync_subscriptions_meta_script_uses_project_relative_paths():
    text = script_text()

    assert "$ProjectRoot = Split-Path -Parent $PSScriptRoot" in text
    assert 'Join-Path $ProjectRoot "scripts\\export_subscriptions_meta.py"' in text
    assert (
        'Join-Path $ProjectRoot "deploy\\vpn-subscription\\subscriptions_meta.generated.json"'
        in text
    )
    assert '$EnvFile = Join-Path $ProjectRoot ".env"' in text


def test_sync_subscriptions_meta_script_fails_fast_when_export_script_is_missing():
    text = script_text()

    assert 'if (-not (Test-Path $ExportScript))' in text
    assert 'throw "Export script not found: $ExportScript"' in text


def test_sync_subscriptions_meta_script_checks_export_exit_code_and_generated_file():
    text = script_text()

    assert "& $Python $ExportScript" in text
    assert 'throw "Export failed with exit code $LASTEXITCODE"' in text
    assert 'if (-not (Test-Path $GeneratedFile))' in text
    assert 'throw "Generated metadata file not found: $GeneratedFile"' in text


def test_sync_subscriptions_meta_script_publishes_atomically_and_checks_exit_codes():
    text = script_text()

    assert "& scp @CommonSshArgs $GeneratedFile $RemoteTempTarget" in text
    assert 'throw "SCP upload failed with exit code $LASTEXITCODE"' in text
    assert "python3 -m json.tool '$RemoteTempPath' >/dev/null" in text
    assert "chmod 0660 '$RemoteTempPath'" in text
    assert "mv -f '$RemoteTempPath' '$($Remote.Path)'" in text
    assert "& ssh @CommonSshArgs $Remote.Host $PublishCommand" in text
    assert 'throw "Remote atomic publish failed with exit code $LASTEXITCODE"' in text
    assert '$CleanupCommand = "rm -f \'$RemoteTempPath\'"' in text


def test_sync_subscriptions_meta_script_prints_operational_context():
    text = script_text()

    assert 'Write-Host "Project root: $ProjectRoot"' in text
    assert 'Write-Host "Python: $Python"' in text
    assert 'Write-Host "Export script: $ExportScript"' in text
    assert 'Write-Host "Generated file: $GeneratedFile"' in text
    assert 'Write-Host "Remote target: $RemoteTarget"' in text


def test_sync_subscriptions_meta_script_validates_local_json_before_upload():
    text = script_text()

    assert 'Write-Host "Validating generated JSON..."' in text
    assert "ConvertFrom-Json | Out-Null" in text
    assert 'throw "Generated metadata is not valid JSON: $GeneratedFile"' in text


def test_sync_subscriptions_meta_script_validates_remote_target_format():
    text = script_text()

    assert "function Parse-RemoteTarget" in text
    assert "Remote target must look like user@host:/absolute/path" in text
    assert "$RemoteTempPath" in text
