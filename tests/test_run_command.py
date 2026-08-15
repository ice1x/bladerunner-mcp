from unittest.mock import MagicMock

import pytest

from bladerunner_mcp.server import MAX_OUTPUT_BYTES, run_command
from tests.conftest import make_stream


@pytest.fixture
def host(write_config, fake):
    write_config(
        {"box": {"host": fake.ipv4(), "user": fake.user_name(), "key_path": "~/.ssh/id_test"}}
    )
    return "box"


def run_responses(exit_code=0, out=b"", err=b"", out_size=None, err_size=None, cleaned=True):
    """Queue for the file-backed run_command: header, stdout head, stderr head[, cleanup]."""
    out_size = len(out) if out_size is None else out_size
    err_size = len(err) if err_size is None else err_size
    header = f"{exit_code}\n{out_size}\n{err_size}\n".encode()
    responses = [(0, header, b""), (0, out, b""), (0, err, b"")]
    if cleaned:
        responses.append((0, b"", b""))
    return responses


def exec_calls(ssh) -> list[str]:
    return [call.args[0] for call in ssh.exec_command.call_args_list]


def test_returns_streams_and_exit_code(ssh, host):
    ssh.responses = run_responses(3, b"hello\n", b"boom\n")
    result = run_command(host, "cmd")
    assert result["stdout"] == "hello\n"
    assert result["stderr"] == "boom\n"
    assert result["exit_code"] == 3
    assert result["truncated"] is False
    assert result["work_dir"] is None


def test_command_runs_in_subshell_with_redirection(ssh, host):
    ssh.responses = run_responses(0, b"", b"")
    run_command(host, "echo hi")
    launch = exec_calls(ssh)[0]
    assert "( echo hi )" in launch
    assert "stdout.log" in launch and "stderr.log" in launch


def test_small_output_cleans_work_dir(ssh, host):
    ssh.responses = run_responses(0, b"ok\n", b"")
    run_command(host, "true")
    assert any(cmd.startswith("rm -rf /tmp/bladerunner_mcp/") for cmd in exec_calls(ssh))


def test_truncated_output_keeps_work_dir(ssh, host):
    head = b"a" * MAX_OUTPUT_BYTES
    ssh.responses = run_responses(0, head, b"", out_size=MAX_OUTPUT_BYTES + 1, cleaned=False)
    result = run_command(host, "big")
    assert result["truncated"] is True
    assert result["stdout_bytes"] == MAX_OUTPUT_BYTES + 1
    assert result["work_dir"].startswith("/tmp/bladerunner_mcp/")
    assert not any(cmd.startswith("rm -rf") for cmd in exec_calls(ssh))


def test_invalid_utf8_is_replaced(ssh, host):
    ssh.responses = run_responses(0, b"\xff\xfeok", b"")
    assert run_command(host, "cmd")["stdout"] == "��ok"


def test_unparseable_header_raises(ssh, host):
    ssh.responses = [(1, b"", b"mkdir: denied\n")]
    with pytest.raises(RuntimeError, match="denied"):
        run_command(host, "true")


def test_command_timeout(ssh, host):
    stream = make_stream()
    stream.channel.exit_status_ready.return_value = False
    ssh.exec_command.side_effect = lambda cmd, timeout=None: (MagicMock(), stream, make_stream())
    with pytest.raises(TimeoutError, match="did not finish"):
        run_command(host, "sleep 999", timeout=0.2)


def test_connect_uses_expanded_key(ssh, host):
    ssh.responses = run_responses()
    run_command(host, "true")
    kwargs = ssh.connect.call_args.kwargs
    assert kwargs["key_filename"].endswith("/.ssh/id_test")
    assert not kwargs["key_filename"].startswith("~")
    assert kwargs["password"] is None


def test_connect_uses_password(ssh, write_config, fake):
    password = fake.password()
    write_config({"pw": {"host": fake.ipv4(), "user": fake.user_name(), "password": password}})
    ssh.responses = run_responses()
    run_command("pw", "true")
    kwargs = ssh.connect.call_args.kwargs
    assert kwargs["password"] == password
    assert kwargs["key_filename"] is None


def test_default_host_key_policy_is_auto_add(ssh, host):
    ssh.responses = run_responses()
    run_command(host, "true")
    ssh.load_system_host_keys.assert_not_called()
    ssh.set_missing_host_key_policy.assert_called_once()


def test_strict_host_key_uses_system_known_hosts(ssh, write_config, fake):
    import paramiko

    write_config(
        {
            "strict": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "strict_host_key": True,
            }
        }
    )
    ssh.responses = run_responses()
    run_command("strict", "true")
    ssh.load_system_host_keys.assert_called_once()
    policy = ssh.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)


def test_connection_error_propagates_and_closes(ssh, host):
    import paramiko

    ssh.connect.side_effect = paramiko.AuthenticationException("denied")
    with pytest.raises(paramiko.AuthenticationException):
        run_command(host, "true")
    ssh.close.assert_called_once()


def test_client_closed_after_success(ssh, host):
    ssh.responses = run_responses()
    run_command(host, "true")
    ssh.close.assert_called_once()


def test_unknown_host_never_connects(ssh, host):
    with pytest.raises(ValueError, match="Unknown host alias"):
        run_command("ghost", "true")
    ssh.connect.assert_not_called()
