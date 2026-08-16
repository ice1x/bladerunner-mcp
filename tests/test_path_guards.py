from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bladerunner_mcp import server
from bladerunner_mcp.server import get_file, put_file, run_command, start_process

OK_RESPONSES = [(0, b"0\n0\n0\n", b""), (0, b"", b""), (0, b"", b""), (0, b"", b"")]


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


@pytest.fixture
def rsync(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(server, "RsyncSSHClient", mock)
    return mock


# ── commands: mutating operation on protected path ──────────────


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /etc/nginx",
        "rm /etc/passwd",
        "mv /etc/passwd /tmp/",
        "chmod -R 777 /usr",
        "chown -R nobody /var/lib/postgresql",
        "truncate -s 0 /etc/crontab",
        "shred /boot/vmlinuz",
        "sed -i 's/a/b/' /etc/hosts",
        "echo pwned > /etc/motd",
        "cat /tmp/x >> /etc/crontab",
        "tee /etc/resolv.conf",
        "sudo rm -rf --no-preserve-root /",
        "rm -rf /",
    ],
)
def test_mutations_on_protected_paths_blocked(ssh, host, command):
    with pytest.raises(ValueError, match="safety filter"):
        run_command(host, command)
    ssh.connect.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp/build",
        "rm -fr ./dist",
        "cat /etc/passwd",
        "ls -la /etc/systemd",
        "grep -r listen /etc/nginx",
        "systemctl status nginx",
        "echo hi > /tmp/out.txt",
        "chmod +x /home/deploy/run.sh",
        "mv /home/deploy/a /home/deploy/b",
    ],
)
def test_reads_and_safe_mutations_pass(ssh, host, command):
    ssh.responses = list(OK_RESPONSES)
    run_command(host, command)
    ssh.connect.assert_called_once()


def test_start_process_also_guarded(ssh, host):
    with pytest.raises(ValueError, match="safety filter"):
        start_process(host, "rm -rf /etc")
    ssh.connect.assert_not_called()


def test_custom_protected_paths_override(ssh, write_config, fake):
    write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "protected_paths": ["/srv/precious"],
            }
        }
    )
    with pytest.raises(ValueError, match="safety filter"):
        run_command("box", "rm -rf /srv/precious/data")
    ssh.responses = list(OK_RESPONSES)
    run_command("box", "rm -rf /etc/nginx")  # default list replaced by override
    ssh.connect.assert_called_once()


def test_allow_dangerous_bypasses_path_guard(ssh, write_config, fake):
    write_config({"yolo": {"host": fake.ipv4(), "user": fake.user_name(), "allow_dangerous": True}})
    ssh.responses = list(OK_RESPONSES)
    run_command("yolo", "rm -rf /etc/nginx")
    ssh.connect.assert_called_once()


# ── transfers: real path validation ─────────────────────────────


def test_put_to_protected_remote_blocked(rsync, host):
    with pytest.raises(ValueError, match="protected"):
        put_file(host, "app.conf", "/etc/nginx/app.conf")
    rsync.assert_not_called()


def test_dotdot_resolved_before_check(rsync, host):
    with pytest.raises(ValueError, match="protected"):
        put_file(host, "x", "/srv/app/../../etc/cron.d/x")
    rsync.assert_not_called()


def test_get_writing_local_ssh_blocked(rsync, host):
    with pytest.raises(ValueError, match="protected"):
        get_file(host, "/srv/app/key", str(Path.home() / ".ssh" / "authorized_keys"))
    rsync.assert_not_called()


def test_put_reading_local_ssh_blocked(rsync, host):
    with pytest.raises(ValueError, match="protected"):
        put_file(host, "~/.ssh/id_ed25519", "/srv/app/key")
    rsync.assert_not_called()


def test_ordinary_transfer_passes(rsync, host):
    put_file(host, "build/", "/srv/app")
    rsync.return_value.put.assert_called_once_with("build/", "/srv/app")


def test_remote_path_must_be_absolute(rsync, host):
    with pytest.raises(ValueError, match="absolute"):
        put_file(host, "x", "srv/app/x")
    rsync.assert_not_called()


def test_allowlist_restricts_remote(rsync, write_config, fake):
    write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "allowed_remote_paths": ["/srv/app", "/var/log/app"],
            }
        }
    )
    get_file("box", "/var/log/app/x.log", "logs/x.log")
    rsync.return_value.get.assert_called_once()
    with pytest.raises(ValueError, match="allowed_remote_paths"):
        put_file("box", "x", "/opt/other/x")


def test_allowlist_restricts_local(rsync, write_config, fake, tmp_path):
    write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "allowed_local_paths": [str(tmp_path)],
            }
        }
    )
    get_file("box", "/srv/app/x", str(tmp_path / "x"))
    rsync.return_value.get.assert_called_once()
    with pytest.raises(ValueError, match="allowed_local_paths"):
        get_file("box", "/srv/app/x", "/opt/elsewhere/x")


def test_allow_dangerous_bypasses_transfer_guard(rsync, write_config, fake):
    write_config({"yolo": {"host": fake.ipv4(), "user": fake.user_name(), "allow_dangerous": True}})
    put_file("yolo", "x", "/etc/cron.d/x")
    rsync.return_value.put.assert_called_once()


@pytest.mark.parametrize(
    "command",
    [
        "cp evil.sh /etc/cron.d/evil",
        "cp -r payload/ /usr/local/bin",
        "rsync -a site/ /etc/nginx",
        "install -m 755 backdoor /sbin/init2",
        "ln -sf /tmp/evil /etc/resolv.conf",
    ],
)
def test_copy_into_protected_paths_blocked(ssh, host, command):
    with pytest.raises(ValueError, match="safety filter"):
        run_command(host, command)
    ssh.connect.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        "cp /etc/passwd /tmp/backup",
        "cp -r /etc /backup/etc-snapshot",
        "rsync -a /var/lib/postgresql /backup/",
        "ln -s /etc/nginx/nginx.conf ./nginx-link",
    ],
)
def test_copy_from_protected_paths_passes(ssh, host, command):
    ssh.responses = list(OK_RESPONSES)
    run_command(host, command)
    ssh.connect.assert_called_once()
