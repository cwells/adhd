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

try:
    import ngrok
except ImportError:
    console.print(f"{Style.WARNING}ngrok-api module not found: ngrok support disabled.")
    ngrok = None

# ==============================================================================


def start_ngrok_agent(
    config: ConfigBox,
    env: dict[str, Any],
    verbose: bool = False,
) -> None:
    if ngrok is None:
        console.print(f"{Style.ERROR}Ngrok support is disabled. Please install ngrok-api package.")
        sys.exit(1)

    client = ngrok.Client(config.api_key)
    for t in client.tunnels.list():
        console.print(t)


# ==============================================================================

key: str | None = "ngrok" if ngrok is not None else None
load: Callable = start_ngrok_agent
target: PluginTarget = PluginTarget.ENV
