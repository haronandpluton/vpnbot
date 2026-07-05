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


def test_sync_subscriptions_meta_script_supports_remote_target_override():
    text = script_text()

    assert "$env:VPN_SUBSCRIPTIONS_META_REMOTE_TARGET" in text
    assert 'return "root@151.243.212.64:/opt/vpn-subscription/subscriptions_meta.json"' in text
    assert "$RemoteTarget = Resolve-RemoteTarget" in text


def test_sync_subscriptions_meta_script_uses_project_relative_paths():
    text = script_text()

    assert "$ProjectRoot = Split-Path -Parent $PSScriptRoot" in text
    assert 'Join-Path $ProjectRoot "scripts\\export_subscriptions_meta.py"' in text
    assert (
        'Join-Path $ProjectRoot "deploy\\vpn-subscription\\subscriptions_meta.generated.json"'
        in text
    )


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


def test_sync_subscriptions_meta_script_checks_scp_exit_code():
    text = script_text()

    assert "scp $GeneratedFile $RemoteTarget" in text
    assert 'throw "SCP upload failed with exit code $LASTEXITCODE"' in text


def test_sync_subscriptions_meta_script_prints_operational_context():
    text = script_text()

    assert 'Write-Host "Project root: $ProjectRoot"' in text
    assert 'Write-Host "Python: $Python"' in text
    assert 'Write-Host "Export script: $ExportScript"' in text
    assert 'Write-Host "Generated file: $GeneratedFile"' in text
    assert 'Write-Host "Remote target: $RemoteTarget"' in text