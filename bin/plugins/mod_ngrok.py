"""
[bold cyan]Configure Ngrok agent.[/]

  ngrok:
    tunnels:
      django:
        addr: 8000
        schemes:
        - https
        inspect: false
        proto: http

This plugin's config mirrors the ngrok config as documented here:

https://ngrok.com/docs/secure-tunnels/ngrok-agent/reference/config/#tunnel-definitions
"""

import sys
from typing import Any, Callable

from lib.plugins import PluginTarget
from lib.util import console, ConfigBox, Style

key: str | None
target: PluginTarget = PluginTarget.ENV
has_run: bool = False


try:
    import ngrok
except ImportError:
    console.print(f"{Style.WARNING}ngrok-api module not found: ngrok support disabled.")
    key = None
else:
    key = "ngrok"


# ==============================================================================


def load(
    config: ConfigBox,
    env: dict[str, Any],
    verbose: bool = False,
) -> None:
    if key is None:
        console.print(f"{Style.ERROR}Ngrok support is disabled. Please install ngrok-api package.")
        sys.exit(1)

    client = ngrok.Client(config.api_key)  # type: ignore
    for t in client.tunnels.list():
        console.print(t)
