import pytest

from bladerunner_mcp.server import check_process, kill_process, start_process


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


def exec_calls(ssh) -> list[str]:
    return [call.args[0] for call in ssh.exec_command.call_args_list]


def test_start_process_returns_pid_and_work_dir(ssh, host):
    ssh.responses = [(0, b"", b""), (0, b"12345\n", b"")]
    result = start_process(host, "sleep 60")
    assert result["pid"] == 12345
    assert result["status"] == "running"
    assert result["work_dir"].startswith("/tmp/bladerunner_mcp/")


def test_start_process_writes_script_with_exit_code_capture(ssh, host):
    ssh.responses = [(0, b"", b""), (0, b"1\n", b"")]
    result = start_process(host, "make all")
    prepare, launch = exec_calls(ssh)
    assert "mkdir -p" in prepare and "run.sh" in prepare
    assert "make all" in prepare and "echo $? >" in prepare
    assert launch.startswith("nohup sh") and result["work_dir"] in launch


def test_start_process_prepare_failure(ssh, host):
    ssh.responses = [(1, b"", b"mkdir: denied\n")]
    with pytest.raises(RuntimeError, match="denied"):
        start_process(host, "true")


def test_start_process_launch_failure(ssh, host):
    ssh.responses = [(0, b"", b""), (0, b"", b"sh: not found\n")]
    with pytest.raises(RuntimeError, match="not found"):
        start_process(host, "true")


def test_check_process_running(ssh, host):
    ssh.responses = [
        (0, b"sh /tmp/bladerunner_mcp/abc/run.sh\n", b""),
        (1, b"", b""),
        (0, b"partial\n", b""),
        (0, b"", b""),
    ]
    result = check_process(host, 42, "/tmp/bladerunner_mcp/abc")
    assert result["status"] == "running"
    assert result["exit_code"] is None
    assert result["stdout_tail"] == "partial\n"


def test_check_process_succeeded(ssh, host):
    ssh.responses = [(0, b"", b""), (0, b"0\n", b""), (0, b"done\n", b""), (0, b"", b"")]
    result = check_process(host, 42, "/tmp/bladerunner_mcp/abc")
    assert (result["status"], result["exit_code"]) == ("succeeded", 0)


def test_check_process_failed(ssh, host):
    ssh.responses = [(0, b"", b""), (0, b"3\n", b""), (0, b"", b""), (0, b"err\n", b"")]
    result = check_process(host, 42, "/tmp/bladerunner_mcp/abc")
    assert (result["status"], result["exit_code"]) == ("failed", 3)
    assert result["stderr_tail"] == "err\n"


def test_check_process_unknown(ssh, host):
    ssh.responses = [(0, b"", b""), (1, b"", b""), (0, b"", b""), (0, b"", b"")]
    result = check_process(host, 42, "/tmp/bladerunner_mcp/abc")
    assert (result["status"], result["exit_code"]) == ("unknown", None)


def test_kill_process(ssh, host):
    ssh.responses = [(0, b"", b"")]
    assert kill_process(host, 42)["killed"] is True
    assert "kill -9 42" in exec_calls(ssh)[0]


def test_kill_process_already_gone(ssh, host):
    ssh.responses = [(1, b"", b"no such process\n")]
    result = kill_process(host, 42)
    assert result["killed"] is False
    assert "no such process" in result["detail"]


def test_check_process_recycled_pid_not_running(ssh, host):
    """A recycled PID with foreign cmdline must not be reported as running."""
    ssh.responses = [
        (0, b"nginx: worker process\n", b""),
        (0, b"0\n", b""),
        (0, b"done\n", b""),
        (0, b"", b""),
    ]
    result = check_process(host, 42, "/tmp/bladerunner_mcp/abc")
    assert (result["status"], result["exit_code"]) == ("succeeded", 0)


def test_check_process_rejects_foreign_work_dir(ssh, host):
    with pytest.raises(ValueError, match="work_dir"):
        check_process(host, 42, "/etc; rm -rf /")
    ssh.connect.assert_not_called()
