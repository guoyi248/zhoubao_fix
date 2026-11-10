import getpass
import warnings
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from system_config.credentials import CredentialUnavailable
from system_config.integrations import effective_config
from system_config.management.commands.encrypt_model_key import Command


@pytest.fixture(autouse=True)
def environment(settings):
    settings.SECRET_KEY = "test-deployment-key"
    settings.LLM_PROVIDER = "openai_compatible"
    settings.LLM_BASE_URL = "https://model.example.test/v1/"
    settings.LLM_API_KEY = ""
    settings.LLM_API_KEY_ENCRYPTED = ""


@pytest.mark.parametrize("from_env", [True, False])
def test_output_is_one_env_assignment_and_can_be_used_without_plaintext(settings, capsys, from_env):
    secret = "test-model-secret-for-command"
    with patch("sys.stdin.isatty", return_value=not from_env), patch("getpass.getpass", return_value=secret) as prompt:
        if from_env:
            settings.LLM_API_KEY = secret
        call_command("encrypt_model_key", from_env=from_env)
        assert prompt.call_count == (0 if from_env else 1)
    output, error = capsys.readouterr()
    assert error == "" and secret not in output
    assert output.splitlines() == [output.rstrip("\n")]
    name, token = output.strip().split("=", 1)
    assert name == "LLM_API_KEY_ENCRYPTED" and token.startswith("v2:")
    assert settings.LLM_API_KEY_ENCRYPTED == ""
    settings.LLM_API_KEY_ENCRYPTED = token
    settings.LLM_API_KEY = ""
    assert effective_config("model", {}, credentials=True)["api_key"] == secret
    settings.LLM_BASE_URL = "https://other.example.test/v1"
    with pytest.raises(CredentialUnavailable):
        effective_config("model", {}, credentials=True)


def test_interactive_read_rejects_non_tty_and_echo_fallback(capsys):
    with patch("sys.stdin.isatty", return_value=False), patch("getpass.getpass") as prompt:
        with pytest.raises(CommandError, match="交互终端"):
            call_command("encrypt_model_key")
        prompt.assert_not_called()

    def unsafe_prompt(_prompt):
        warnings.warn("terminal echoes input", getpass.GetPassWarning)
        pytest.fail("getpass must stop before reading echoed input")

    with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", side_effect=unsafe_prompt):
        with pytest.raises(CommandError, match="安全读取"):
            call_command("encrypt_model_key")
    assert capsys.readouterr().out == ""


def test_rejects_missing_env_key_and_invalid_destination(settings):
    with pytest.raises(CommandError, match="去掉 --from-env"):
        call_command("encrypt_model_key", "--from-env")
    settings.LLM_API_KEY = "dummy-key"
    settings.LLM_BASE_URL = "https://model.example.test/?key=must-not-appear"
    with pytest.raises(CommandError, match="LLM_BASE_URL") as error:
        call_command("encrypt_model_key", "--from-env")
    assert "must-not-appear" not in str(error.value)
    settings.LLM_PROVIDER = "wrong"
    with pytest.raises(CommandError, match="LLM_PROVIDER"):
        call_command("encrypt_model_key", "--from-env")


def test_command_rejects_positional_key_without_echoing_it(capsys):
    secret = "accidentally-pasted-api-key"
    with pytest.raises(SystemExit) as error:
        Command(stdout=StringIO()).run_from_argv(["manage.py", "encrypt_model_key", secret])
    assert error.value.code == 2
    output, diagnostic = capsys.readouterr()
    assert output == "" and secret not in diagnostic
    assert "--from-env" in diagnostic
