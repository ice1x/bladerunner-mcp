import pytest

from bladerunner_mcp.server import run_command


@pytest.fixture
def host(write_config, fake):
    write_config(
        {"box": {"host": fake.ipv4(), "user": fake.user_name(), "key_path": "~/.ssh/id_test"}}
    )
    return "box"


def test_returns_stdout_stderr_exit_code(ssh, host):
    ssh.responses = [(0, b"hello\n", b"")]
    assert run_command(host, "echo hello") == {"stdout": "hello\n", "stderr": "", "exit_code": 0}


def test_nonzero_exit_code(ssh, host):
    ssh.responses = [(2, b"", b"boom\n")]
    assert run_command(host, "false") == {"stdout": "", "stderr": "boom\n", "exit_code": 2}


def test_connect_uses_expanded_key(ssh, host):
    run_command(host, "true")
    kwargs = ssh.connect.call_args.kwargs
    assert kwargs["key_filename"].endswith("/.ssh/id_test")
    assert not kwargs["key_filename"].startswith("~")
    assert kwargs["password"] is None


def test_connect_uses_password(ssh, write_config, fake):
    password = fake.password()
    write_config({"pw": {"host": fake.ipv4(), "user": fake.user_name(), "password": password}})
    run_command("pw", "true")
    kwargs = ssh.connect.call_args.kwargs
    assert kwargs["password"] == password
    assert kwargs["key_filename"] is None


def test_connection_error_propagates_and_closes(ssh, host):
    ssh.connect.side_effect = OSError("unreachable")
    with pytest.raises(OSError, match="unreachable"):
        run_command(host, "true")
    ssh.close.assert_called_once()


def test_client_closed_after_success(ssh, host):
    run_command(host, "true")
    ssh.close.assert_called_once()


def test_unknown_host_never_connects(ssh, host):
    with pytest.raises(ValueError, match="Unknown host alias"):
        run_command("ghost", "true")
    ssh.connect.assert_not_called()
