import paramiko
import pytest

from bladerunner_mcp import server
from bladerunner_mcp.server import run_command
from tests.test_run_command import run_responses


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(server, "RETRY_DELAYS", (0, 0))


def test_transient_connect_errors_retried(ssh, host):
    ssh.connect.side_effect = [paramiko.SSHException("flaky"), OSError("reset"), None]
    ssh.responses = run_responses()
    run_command(host, "true")
    assert ssh.connect.call_count == 3


def test_auth_error_not_retried(ssh, host):
    ssh.connect.side_effect = paramiko.AuthenticationException("bad key")
    with pytest.raises(paramiko.AuthenticationException):
        run_command(host, "true")
    assert ssh.connect.call_count == 1


def test_missing_key_file_not_retried(ssh, host):
    ssh.connect.side_effect = FileNotFoundError("~/.ssh/id_missing")
    with pytest.raises(FileNotFoundError):
        run_command(host, "true")
    assert ssh.connect.call_count == 1


def test_transient_errors_exhaust_retries(ssh, host):
    ssh.connect.side_effect = OSError("unreachable")
    with pytest.raises(OSError, match="unreachable"):
        run_command(host, "true")
    assert ssh.connect.call_count == 3
    assert ssh.close.call_count == 3
