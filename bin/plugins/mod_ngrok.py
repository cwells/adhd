"""
[bold cyan]Configure Ngrok agent.[/] [bold white]This plugin is largely fictional.[/]

  ngrok:
    always: true
    config:
      version: "2"
      authtoken: <auth_token>
      api_key: <api_key>
      console_ui: false
      log: ~/ngrok.log
      tunnels:
        django:
          addr: 8000
          schemes: [ https ]
          inspect: false
          proto: http

This plugin's config mirrors the ngrok config as documented here:

https://ngrok.com/docs/secure-tunnels/ngrok-agent/reference/config/#tunnel-definitions
"""

import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Generator

import yaml
from yarl import URL

from lib.boot import missing_modules
from lib.plugins import BasePlugin, PluginTarget
from lib.util import ConfigBox, Style, console
from lib.shell import shell

if missing_modules(["ngrok"]):
    console.print(f"{Style.WARNING}ngrok-api module not found: ngrok support disabled.")
    ngrok = None
else:
    import ngrok


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "ngrok"
    enabled: bool = ngrok is not None
    target: PluginTarget | None = None
    has_run: bool = False

    def load(
        self,
        config: ConfigBox,
        env: dict[str, Any],
        silent: bool = False,
        verbose: bool = False,
        debug: bool = False,
    ) -> None:
        "Start the ngrok agent."

        if not self.enabled:
            console.print(f"{Style.ERROR}Ngrok support is disabled. Please install ngrok-api package.")
            sys.exit(1)

        for tunnel in self.list_tunnels(config.config):
            if tunnel["up"] and not silent:
                console.print(f"{Style.SKIPPED}tunnel {tunnel['name']}.")
            else:
                self.start_tunnel(tunnel["name"], config, env, silent=silent, verbose=verbose, debug=debug)

    def start_tunnel(
        self,
        tunnel: str | None,
        config: ConfigBox,
        env: dict[str, Any],
        silent: bool = False,
        verbose: bool = False,
        debug: bool = False,
    ) -> None:
        "Use the ngrok agent rather than API as we exit and can't maintain our own tunnel."

        tmpdir: Path = Path(config["tmp"])
        tun: str = tunnel or config["default"]

        config.config["console_ui"] = False

        if not tun in config.config.get("tunnels", []):
            console.print(f"{Style.ERROR}Tunnel {tun} not found in ngrok.config.tunnels.")
            sys.exit(1)

        with NamedTemporaryFile(dir=tmpdir, mode="w+", suffix=".yml") as tmpfile:
            yaml.dump(config.config.to_dict(), tmpfile, default_flow_style=False)
            tmpfile.flush()
            tmpfile.seek(0)

            if not silent:
                console.print(f"{Style.STARTING}tunnel {tun}.")

            shell(f"ngrok --config {tmpfile.name} start {tun} &", env=env, interactive=True)
            time.sleep(2)  # give ngrok time to read config

    def stop_tunnel(self, config: ConfigBox, env: dict[str, Any]) -> None:
        client = ngrok.Client(config.api_key)  # type: ignore

    def list_tunnels(self, config: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
        client = ngrok.Client(config.api_key)  # type: ignore
        tunnels = {t.forwards_to: t for t in client.tunnels.list()}

        for t in config["tunnels"]:
            addr = config["tunnels"][t]["addr"]
            if addr in tunnels:
                yield {
                    "name": t,
                    "id": tunnels[addr].id,
                    "public_url": tunnels[addr].public_url,
                    "addr": addr,
                    "up": True,
                }
            else:
                yield {
                    "name": t,
                    "addr": addr,
                    "up": False,
                }
