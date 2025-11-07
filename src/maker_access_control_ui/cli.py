#!/usr/bin/env python3
"""Minimal command-line interface for the Maker Access Control demo provider."""

from __future__ import annotations

import argparse
from typing import Callable

from maker_access_control_ui.access.provider import AccessProvider
from maker_access_control_ui.access.provider import get_provider


def _handle_check_access(provider: AccessProvider, args: argparse.Namespace) -> None:
    print("ALLOW" if provider.check_access(args.rfid, args.device) else "DENY")


def _handle_set_person(provider: AccessProvider, args: argparse.Namespace) -> None:
    provider.upsert_person(args.user, args.rfid)
    print("OK")


def _handle_set_tool(provider: AccessProvider, args: argparse.Namespace) -> None:
    provider.upsert_tool(args.tool, args.device, args.name)
    print("OK")


def _handle_grant(provider: AccessProvider, args: argparse.Namespace) -> None:
    provider.grant(args.user, args.tool)
    print("OK")


def _handle_revoke(provider: AccessProvider, args: argparse.Namespace) -> None:
    provider.revoke(args.user, args.tool)
    print("OK")


def _handle_list_people(provider: AccessProvider, _: argparse.Namespace) -> None:
    for person in provider.list_people():
        print(f'{person["id"]}\t{person.get("rfid", "")}')


def _handle_list_tools(provider: AccessProvider, _: argparse.Namespace) -> None:
    for tool in provider.list_tools():
        print(f'{tool["id"]}\t{tool.get("device_id", "")}\t{tool.get("name", "")}')


def _handle_list_assignments(provider: AccessProvider, _: argparse.Namespace) -> None:
    for user_id, tool_id in provider.list_assignments():
        print(f"{user_id}\t{tool_id}")


HANDLERS: dict[str, Callable[[AccessProvider, argparse.Namespace], None]] = {
    "check-access": _handle_check_access,
    "set-person": _handle_set_person,
    "set-tool": _handle_set_tool,
    "grant": _handle_grant,
    "revoke": _handle_revoke,
    "list-people": _handle_list_people,
    "list-tools": _handle_list_tools,
    "list-assignments": _handle_list_assignments,
}


def main() -> None:
    """Parse arguments and dispatch to the appropriate provider helper."""
    parser = argparse.ArgumentParser(prog="maker-access-control")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check-access")
    p_check.add_argument("--rfid", required=True)
    p_check.add_argument("--device", required=True)

    p_sp = sub.add_parser("set-person")
    p_sp.add_argument("--user", required=True)
    p_sp.add_argument("--rfid", required=True)

    p_st = sub.add_parser("set-tool")
    p_st.add_argument("--tool", required=True)
    p_st.add_argument("--device", required=True)
    p_st.add_argument("--name", default=None)

    p_grant = sub.add_parser("grant")
    p_grant.add_argument("--user", required=True)
    p_grant.add_argument("--tool", required=True)

    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("--user", required=True)
    p_revoke.add_argument("--tool", required=True)

    sub.add_parser("list-people")
    sub.add_parser("list-tools")
    sub.add_parser("list-assignments")

    args = parser.parse_args()
    provider = get_provider()
    handler = HANDLERS[args.cmd]
    handler(provider, args)


if __name__ == "__main__":
    main()
