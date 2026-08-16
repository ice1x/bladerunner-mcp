import pytest

from bladerunner_mcp.server import run_command, start_process

OK_RESPONSES = [(0, b"0\n0\n0\n", b""), (0, b"", b""), (0, b"", b""), (0, b"", b"")]


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


@pytest.fixture
def yolo_host(write_config, fake):
    write_config({"yolo": {"host": fake.ipv4(), "user": fake.user_name(), "allow_dangerous": True}})
    return "yolo"


@pytest.mark.parametrize(
    "command",
    [
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
        "reboot",
        "echo hi; poweroff",
        ":(){ :|:& };:",
        'psql -c "DROP TABLE users;"',
        "mysql -e 'drop database prod'",
    ],
)
def test_catastrophic_commands_blocked(ssh, host, command):
    with pytest.raises(ValueError, match="safety filter"):
        run_command(host, command)
    ssh.connect.assert_not_called()


def test_catastrophic_command_blocked_in_start_process(ssh, host):
    with pytest.raises(ValueError, match="safety filter"):
        start_process(host, "shutdown -h now")
    ssh.connect.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        "ls -la /var/lib",
        "systemctl status nginx",
        "grep -r 'shutdown_hook' src/",
        "echo 'dd is a tool'",
    ],
)
def test_ordinary_commands_pass(ssh, host, command):
    ssh.responses = list(OK_RESPONSES)
    run_command(host, command)
    ssh.connect.assert_called_once()


def test_allow_dangerous_host_bypasses_filter(ssh, yolo_host):
    ssh.responses = list(OK_RESPONSES)
    run_command(yolo_host, "shutdown -h now")
    ssh.connect.assert_called_once()
