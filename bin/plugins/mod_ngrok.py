"""
[bold cyan]Configure Ngrok agent.[/] [bold white]This plugin is largely fictional.[/]

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
from typing import Any

from lib.boot import missing_modules
from lib.plugins import BasePlugin, PluginTarget
from lib.util import ConfigBox, Style, console

if missing_modules(["ngrok"]):
    console.print(f"{Style.WARNING}ngrok-api module not found: ngrok support disabled.")
    ngrok = None
else:
    import ngrok


# ==============================================================================


class Plugin(BasePlugin):
    key: str | None = None
    enabled: bool = False
    target: PluginTarget = PluginTarget.CONF
    has_run: bool = False

    def load(
        self,
        config: ConfigBox,
        env: dict[str, Any],
        verbose: bool = False,
    ) -> None:
        if not self.enabled:
            console.print(f"{Style.ERROR}Ngrok support is disabled. Please install ngrok-api package.")
            sys.exit(1)

        client = ngrok.Client(config.api_key)  # type: ignore
        for t in client.tunnels.list():
            console.print(t)
