from pathlib import Path


LAUNCHER = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "start-windows.ps1"
)


def launcher_text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_launcher_exists_and_uses_windows_credential_api() -> None:
    text = launcher_text()

    assert LAUNCHER.is_file()
    assert 'EntryPoint = "CredReadW"' in text
    assert 'private static extern void CredFree' in text
    assert 'CredFree(credentialPointer);' in text
    assert "int secretLength = checked((int)credential.CredentialBlobSize);" in text
    assert "Array.Clear(secretBytes, 0, secretBytes.Length);" in text


def test_launcher_reads_only_named_adp_credentials() -> None:
    text = launcher_text()

    assert "'ADP_SLACK_BOT_TOKEN'" in text
    assert "'ADP_SLACK_APP_TOKEN'" in text
    assert "ADP_SLACK_SIGNING_SECRET" not in text


def test_launcher_passes_secrets_only_through_child_environment() -> None:
    text = launcher_text()

    assert "$processInfo.UseShellExecute = $false" in text
    assert "$processInfo.EnvironmentVariables['SLACK_BOT_TOKEN'] = $botToken" in text
    assert "$processInfo.EnvironmentVariables['SLACK_APP_TOKEN'] = $appToken" in text
    assert "$processInfo.Arguments = '-m adp_orchestrator.app'" in text
    assert "SLACK_BOT_TOKEN=" not in text
    assert "SLACK_APP_TOKEN=" not in text


def test_launcher_matches_application_lease_validation() -> None:
    text = launcher_text()

    assert "[ValidateRange(30, 86400)]" in text


def test_launcher_resolves_relative_python_path_from_project_root() -> None:
    text = launcher_text()

    assert "[System.IO.Path]::IsPathRooted($PythonCommand)" in text
    assert "(Join-Path $projectRoot $PythonCommand)" in text
    assert "$processInfo.FileName = $resolvedPythonCommand" in text


def test_launcher_does_not_create_or_copy_dotenv() -> None:
    text = launcher_text().lower()

    assert "copy-item" not in text
    assert "set-content" not in text
    assert "out-file" not in text
    assert "new-item" not in text
    assert "not written to .env" in text


def test_launcher_clears_secret_references_and_process_in_finally() -> None:
    text = launcher_text()

    assert "$processInfo = $null" in text
    assert "$processInfo.EnvironmentVariables.Remove('SLACK_BOT_TOKEN')" in text
    assert "$processInfo.EnvironmentVariables.Remove('SLACK_APP_TOKEN')" in text
    assert "$process.Dispose()" in text
    assert "$botToken = $null" in text
    assert "$appToken = $null" in text


def test_launcher_errors_name_credentials_without_echoing_values() -> None:
    text = launcher_text()

    assert "Credential could not be read" in text
    assert "has an empty password" in text
    assert "is not a Slack Bot Token" in text
    assert "is not a Slack App-Level Token" in text
    assert "Write-Host $botToken" not in text
    assert "Write-Output $botToken" not in text
    assert "Write-Host $appToken" not in text
    assert "Write-Output $appToken" not in text
