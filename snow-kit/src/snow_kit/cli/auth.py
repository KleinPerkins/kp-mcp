"""Browser SSO helper subcommands for snow-kit (login / status / logout)."""
from __future__ import annotations

import json
import sys

from snow_kit.bootstrap import SERVER_NAME
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import SnowflakeSession


def run_auth(args: list[str]) -> int:
    """Dispatch the ``auth`` subcommand."""
    sub = args[0] if args else "status"
    if sub == "status":
        config = SnowKitConfig.from_env()
        configured = bool(config.account and config.user)
        print(
            json.dumps(
                {
                    "server": SERVER_NAME,
                    "state": "needs_sign_in" if configured else "needs_setup",
                    "authenticator": config.authenticator,
                    "configured": {
                        "account": bool(config.account),
                        "user": bool(config.user),
                        "database": bool(config.database),
                        "warehouse": bool(config.warehouse),
                    },
                    "next_action": (
                        "Run `snow-kit auth login` to verify or establish the SSO session."
                        if configured
                        else "Run `snow-kit setup` with account and user."
                    ),
                },
                sort_keys=True,
            )
        )
        return 0
    if sub == "logout":
        print(f"{SERVER_NAME}: browser SSO uses Snowflake connector/session cache; close browser sessions manually if needed")
        return 0
    if sub == "login":
        session = SnowflakeSession()
        try:
            context = session.current_context()
            print(json.dumps({"server": SERVER_NAME, "status": "connected", "context": context}, sort_keys=True, default=str))
            return 0
        finally:
            session.close()
    print(f"error: unknown auth subcommand {sub!r}", file=sys.stderr)
    return 2
