import pytest

from bladerunner_mcp.server import MAX_OUTPUT_BYTES, read_output

WORK_DIR = "/tmp/bladerunner_mcp/abc123"


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


def exec_calls(ssh) -> list[str]:
    return [call.args[0] for call in ssh.exec_command.call_args_list]


def test_reads_slice(ssh, host):
    ssh.responses = [(0, b"150\n", b""), (0, b"abc", b"")]
    result = read_output(host, WORK_DIR, offset=10, length=3)
    assert result == {"data": "abc", "offset": 10, "bytes": 3, "total_bytes": 150, "eof": False}
    assert any("tail -c +11" in cmd for cmd in exec_calls(ssh))


def test_last_page_reports_eof(ssh, host):
    ssh.responses = [(0, b"5\n", b""), (0, b"de", b"")]
    result = read_output(host, WORK_DIR, offset=3, length=10)
    assert (result["bytes"], result["eof"]) == (2, True)


def test_offset_beyond_eof(ssh, host):
    ssh.responses = [(0, b"5\n", b""), (0, b"", b"")]
    result = read_output(host, WORK_DIR, offset=10)
    assert (result["data"], result["bytes"], result["eof"]) == ("", 0, True)


def test_stderr_stream(ssh, host):
    ssh.responses = [(0, b"3\n", b""), (0, b"err", b"")]
    read_output(host, WORK_DIR, stream="stderr")
    assert any("stderr.log" in cmd for cmd in exec_calls(ssh))


def test_length_clamped_to_max(ssh, host):
    ssh.responses = [(0, b"10\n", b""), (0, b"x", b"")]
    read_output(host, WORK_DIR, length=10**9)
    assert any(f"head -c {MAX_OUTPUT_BYTES}" in cmd for cmd in exec_calls(ssh))


def test_invalid_stream_rejected(ssh, host):
    with pytest.raises(ValueError, match="stream"):
        read_output(host, WORK_DIR, stream="config")
    ssh.connect.assert_not_called()


def test_invalid_work_dir_rejected(ssh, host):
    with pytest.raises(ValueError, match="work_dir"):
        read_output(host, "/etc; rm -rf /")
    ssh.connect.assert_not_called()


def test_missing_output_raises(ssh, host):
    ssh.responses = [(1, b"", b"No such file or directory\n")]
    with pytest.raises(RuntimeError, match="No such file"):
        read_output(host, WORK_DIR)
