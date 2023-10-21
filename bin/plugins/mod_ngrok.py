"""
Configure ngrok agent.

This plugin's config mirrors the ngrok config as documented here:

[u]https://ngrok.com/docs/secure-tunnels/ngrok-agent/reference/config[/u]

[bold]Notes[/]:
While this plugin allows you to define multple tunnels, the ngrok free tier only allows a single active tunnel, and as such, only the first defined tunnel will be started. Set the [blue]subscribed[/] attribute to [blue]true[/] if you have a paid account to start additional tunnels (untested).

[blue]console_ui[/] is autoload set to [blue]false[/].

[cyan]unplug:ngrok[/] should be called when stopping the stack as otherwise the tunnel will remain up.

[bold]Public methods:[/]
:white_circle:[cyan]plugin:ngrok.status[/]: Prints the status of defined tunnels. Does not require plugin to be loaded.

"""

example = """
plugins:
  ngrok:
    autoload: true
    subscribed: false
    config:
      authtoken: "<auth_token>"
      api_key: "<api_key>"
      version: "2"
      log: ~/ngrok.log
      tunnels:
        django:
          addr: 8000
          schemes: [ https ]
          inspect: false
          proto: http
"""

required_modules: dict[str, str] = {"ngrok": "ngrok-api", "psutil": "psutil"}
required_binaries: list[str] = ["ngrok"]

import sys
import time
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Generator
from types import ModuleType

import ruamel.yaml as yaml
from lib.boot import missing_binaries, missing_modules
from lib.shell import shell
from lib.util import ConfigBox, Style, console, ConfigBox
from plugins import BasePlugin, MetadataType, public

missing_mods: list[str]
missing_bins: list[str]

if missing_mods := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]ngrok[/] disabled, missing modules: {', '.join(missing_mods)}\n")
else:
    import ngrok
    import psutil

if missing_bins := missing_binaries(required_binaries):
    console.print(f"Plugin [bold blue]ngrok[/] disabled, missing binaries: {', '.join(missing_bins)}\n")


# ==============================================================================


class Plugin(BasePlugin):
    "Configure ngrok agent."

    key: str = "ngrok"
    enabled: bool = not (missing_mods or missing_bins)

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Start the ngrok agent."

        if not self.enabled:
            self.print(f"support is disabled. Please install plugin requirements.", Style.ERROR)
            sys.exit(1)

        plugin_config: ConfigBox = config.plugins[self.key]
        subscribed: bool = plugin_config.get("subscribed", False)
        active_tunnels: list[dict] = [t for t in self.list_tunnels(plugin_config.config)]

        if not any(t for t in active_tunnels if t["up"]) or subscribed:
            for tunnel in active_tunnels:
                if tunnel["up"] and self.verbose:
                    self.print(f"tunnel {tunnel['name']}.", Style.PLUGIN_SKIP)
                else:
                    self.start_tunnel(tunnel["name"], plugin_config, env)

                if not subscribed:  # free tier only allows one active tunnel
                    break

        self.events.exit.append(partial(self.status, tuple(), plugin_config, env))
        self.metadata["vars"].update({"tunnels": self.list_tunnels(plugin_config)})

        return self.metadata

    def start_tunnel(
        self,
        tunnel: str | None,
        config: ConfigBox,
        env: ConfigBox,
    ) -> None:
        "Use the ngrok agent rather than API as we exit and can't be our own agent."

        tmpdir: Path = Path(config["tmp"])

        config.config["console_ui"] = False

        if not config.config.get("tunnels", []):
            self.print_error(f"Tunnel definitions not found in ngrok config.")
            sys.exit(1)

        with console.status("Loading ngrok plugin") as status:
            with NamedTemporaryFile(dir=tmpdir, mode="w+", suffix=".yml") as tmpfile:
                yaml.dump(config.config.to_dict(), tmpfile, default_flow_style=False)
                tmpfile.flush()
                tmpfile.seek(0)

                if self.verbose or self.debug:
                    status.update(rf"Starting ngrok tunnel [bold blue]{tunnel}[/].")

                shell(f"ngrok --config {tmpfile.name} start {tunnel} &", env=env, interactive=True)
                time.sleep(3)  # give ngrok time to read config before it's gone

    def unload(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Kill the ngrok agent, terminating all tunnels."

        with console.status("Terminating ngrok tunnels") as status:
            while any(t["up"] for t in self.list_tunnels(config.config)):
                processes: list[psutil.Process] = [
                    proc for proc in psutil.process_iter(attrs=["name"]) if proc.name() == "ngrok"
                ]
                proc: psutil.Process
                alive: list[psutil.Process]

                if self.verbose:
                    status.update(f"Waiting for tunnels to stop")

                for proc in processes:
                    proc.terminate()
                _, alive = psutil.wait_procs(processes, timeout=3)
                for proc in alive:
                    proc.kill()

        return self.metadata

    def list_tunnels(self, config: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
        "We only get the actual ngrok config here, e.g. plugins.ngrok.config"

        client: ngrok.Client = ngrok.Client(config.api_key)  # type: ignore
        tunnels: dict = {t.forwards_to: t for t in client.tunnels.list()}

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

    @public()
    def status(self, args: tuple[str, ...], config: ConfigBox, env: ConfigBox) -> None:
        "Print the status of configured ngrok tunnels."

        console.print(f"{Style.PLUGIN_INFO}[bold cyan]ngrok[/] public endpoints:")

        for t in self.list_tunnels(config.config):
            if t["up"]:
                console.print(
                    f"  {Style.UP}tunnel "
                    "[bold cyan]{name}[/] is [bold green]up[/]:   [u]{addr}[/u] <- [u]{public_url}[/u]".format(**t)
                )
            else:
                console.print(
                    f"  {Style.DOWN}tunnel " "[bold cyan]{name}[/] is [bold red]down[/]: [u]{addr}[/u]".format(**t)
                )

        console.print()
