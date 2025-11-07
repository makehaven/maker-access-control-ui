"""Coverage for the Maker Access Control command-line interface."""

from __future__ import annotations

from tests.maker_ui._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui import cli  # noqa: E402


def test_cli_check_access(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "maker-access-control",
            "check-access",
            "--rfid",
            "01020304",
            "--device",
            "test_tool_a_activator",
        ],
    )
    cli.main()


def test_cli_grant(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["maker-access-control", "grant", "--user", "u.bob", "--tool", "t.tool_b"],
    )
    cli.main()
    captured = capsys.readouterr()
    assert "OK" in captured.out

    monkeypatch.setattr(
        "sys.argv",
        [
            "maker-access-control",
            "check-access",
            "--rfid",
            "A1B2C3D4",
            "--device",
            "test_tool_b_activator",
        ],
    )
    cli.main()
    captured = capsys.readouterr()
    assert "ALLOW" in captured.out
