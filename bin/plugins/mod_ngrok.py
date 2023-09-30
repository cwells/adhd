"""
[bold cyan]Configure Ngrok agent.[/]

  ngrok:
    always: true
    subscribed: false
    config:
      authtoken: <auth_token>
      api_key: <api_key>
      version: "2"
      log: ~/ngrok.log
      tunnels:
        django:
          addr: 8000
          schemes: [ https ]
          inspect: false
          proto: http

This plugin's config mirrors the ngrok config as documented here:

https://ngrok.com/docs/secure-tunnels/ngrok-agent/reference/config

[bold]Notes[/]:

While this plugin allows you to define multple tunnels, the ngrok free tier only
allows a single active tunnel, and as such, only the first defined tunnel will be
started. Set the [blue]subscribed[/] attribute to [blue]true[/] to start additional tunnels.

[blue]console_ui[/] is always set to [blue]false[/].

[blue]unplug:ngrok[/] should be called when destroying the stack as otherwise the
tunnel will remain up.
"""

import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Generator

import yaml

from lib.boot import missing_modules
from lib.plugins import BasePlugin, PluginTarget
from lib.util import ConfigBox, Style, console
from lib.shell import shell

if missing := missing_modules(["ngrok", "psutil"]):
    console.print(f"Plugin [bold blud]ngrok[/] disabled, missing modules: {', '.join(missing)}\n")
    ngrok = None
else:
    import ngrok
    import psutil


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

        subscribed: bool = config.get("subscribed", False)

        for tunnel in self.list_tunnels(config.config):
            if tunnel["up"] and not silent:
                console.print(f"{Style.SKIPPED}tunnel {tunnel['name']}.")
            else:
                self.start_tunnel(tunnel["name"], config, env, silent=silent, verbose=verbose, debug=debug)

            if not subscribed:  # free tier only allows one active tunnel
                break

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

        config.config["console_ui"] = False

        if not config.config.get("tunnels", []):
            console.print(f"{Style.ERROR}Tunnel definitions not found in ngrok config.")
            sys.exit(1)

        with NamedTemporaryFile(dir=tmpdir, mode="w+", suffix=".yml") as tmpfile:
            yaml.dump(config.config.to_dict(), tmpfile, default_flow_style=False)
            tmpfile.flush()
            tmpfile.seek(0)

            if not silent:
                console.print(rf"{Style.STARTING} ngrok tunnel \[[bold blue]{tunnel}[/]].")

            shell(f"ngrok --config {tmpfile.name} start {tunnel} &", env=env, interactive=True)
            time.sleep(2)  # give ngrok time to read config before it's gone

    def unload(self, config: ConfigBox, env: dict[str, Any]) -> list[str] | None:
        "We can't manage individual tunnels on free plan, so just kill the process."

        if not self.has_run:
            return

        if not "ngrok" in config.get("plugins", []):
            return

        if not "config" in config.plugins.ngrok:
            return

        if any(t["up"] for t in self.list_tunnels(config.plugins.ngrok.config)):
            for proc in psutil.process_iter():
                if proc.name() == "ngrok":
                    proc.kill()

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
