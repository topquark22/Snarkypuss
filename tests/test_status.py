"""Tests for read-only local gateway status collectors."""

import subprocess
from pathlib import Path

import pytest

from snarkyctl.status import (
    CommandResult,
    StatusCollectionError,
    collect_dns_status,
    collect_system_status,
    collect_local_status,
    run_command,
)


def test_dns_status_parses_systemd_properties() -> None:
    def runner(_path: Path, arguments: tuple[str, ...], _timeout: float) -> CommandResult:
        assert arguments[0:2] == ("show", "dnsmasq.service")
        return CommandResult(
            0,
            "LoadState=loaded\nActiveState=active\nSubState=running\n",
            "",
        )

    status = collect_dns_status(runner)

    assert status.service == "dnsmasq.service"
    assert status.active_state == "active"
    assert status.sub_state == "running"


def test_command_runner_uses_fixed_argument_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="ok", stderr="")

    monkeypatch.setattr("snarkyctl.status.subprocess.run", fake_run)

    result = run_command(Path("/usr/bin/systemctl"), ("show", "dnsmasq.service"), 5)

    assert result.stdout == "ok"
    assert captured == [["/usr/bin/systemctl", "show", "dnsmasq.service"]]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileNotFoundError(), "COMMAND_NOT_FOUND"),
        (PermissionError(), "COMMAND_PERMISSION_DENIED"),
        (subprocess.TimeoutExpired("systemctl", 5), "COMMAND_TIMEOUT"),
    ],
)
def test_command_runner_maps_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    code: str,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("snarkyctl.status.subprocess.run", fail)

    with pytest.raises(StatusCollectionError) as error:
        run_command(Path("/usr/bin/systemctl"), ("show", "dnsmasq.service"), 5)

    assert error.value.code == code


def test_command_runner_rejects_oversized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="x" * 20000, stderr="")

    monkeypatch.setattr("snarkyctl.status.subprocess.run", fake_run)

    with pytest.raises(StatusCollectionError) as error:
        run_command(Path("/usr/bin/systemctl"), ("show", "dnsmasq.service"), 5)

    assert error.value.code == "COMMAND_OUTPUT_TOO_LARGE"


def test_dns_status_reports_command_failure() -> None:
    with pytest.raises(StatusCollectionError) as error:
        collect_dns_status(lambda *_args: CommandResult(1, "", "unit unavailable\n"))

    assert error.value.code == "DNS_STATUS_FAILED"
    assert "unit unavailable" in str(error.value)


def test_dns_status_rejects_incomplete_output() -> None:
    with pytest.raises(StatusCollectionError) as error:
        collect_dns_status(lambda *_args: CommandResult(0, "ActiveState=active\n", ""))

    assert error.value.code == "DNS_STATUS_INVALID"


def test_system_status_reads_procfs_and_disk(tmp_path: Path) -> None:
    uptime = tmp_path / "uptime"
    meminfo = tmp_path / "meminfo"
    uptime.write_text("183642.75 0.0\n", encoding="ascii")
    meminfo.write_text(
        "MemTotal:       2048000 kB\nMemAvailable:   1294336 kB\n",
        encoding="ascii",
    )

    status = collect_system_status(
        uptime_path=uptime,
        meminfo_path=meminfo,
        load_average=lambda: (0.08, 0.11, 0.09),
        disk_usage=lambda _path: type("Disk", (), {"total": 1000, "free": 400})(),
    )

    assert status.uptime_seconds == 183642
    assert status.load_average == (0.08, 0.11, 0.09)
    assert status.memory_total_bytes == 2048000 * 1024
    assert status.memory_available_bytes == 1294336 * 1024
    assert status.root_disk_total_bytes == 1000
    assert status.root_disk_free_bytes == 400


def test_system_status_maps_malformed_procfs_to_controlled_failure(tmp_path: Path) -> None:
    uptime = tmp_path / "uptime"
    meminfo = tmp_path / "meminfo"
    uptime.write_text("not-a-number\n", encoding="ascii")
    meminfo.write_text("", encoding="ascii")

    with pytest.raises(StatusCollectionError) as error:
        collect_system_status(uptime_path=uptime, meminfo_path=meminfo)

    assert error.value.code == "SYSTEM_STATUS_FAILED"


def test_local_status_retains_independent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "snarkyctl.status.collect_dns_status",
        lambda: (_ for _ in ()).throw(
            StatusCollectionError("DNS_STATUS_FAILED", "dns failed")
        ),
    )
    monkeypatch.setattr(
        "snarkyctl.status.collect_system_status",
        lambda: (_ for _ in ()).throw(
            StatusCollectionError("SYSTEM_STATUS_FAILED", "system failed")
        ),
    )

    dns, system, failures = collect_local_status()

    assert dns is None
    assert system is None
    assert [failure.component for failure in failures] == ["dns", "system"]
