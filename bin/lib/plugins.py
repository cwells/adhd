"""
Plugins can do pretty much anything, but they can only directly affect two aspects
of `adhd`: configuration and environment. This is done by way of their return
value, which is always a dictionary and will be merged with the relevant part
of the execution environment.

`Plugin.target` may be one of:
- `PluginTarget.ENV`: merge return value with environment
- `PluginTarget.CONF`: merge return value with configuration
- `None`: ignore any return value

Plugins are only run once, either at boot time (if `always: true` is specified
in plugin configuration), or on-demand, if they are specified as a dependency
for a job (e.g. `after: plugin:python`).
"""

import importlib
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any

import rich.prompt

from .util import ConfigBox, Style, console, get_program_bin, realize

# ==============================================================================


class PluginTarget(Enum):
    "Plugins can update either environment, configuration, or None."

    ENV = "env"
    CONF = "conf"


class BasePlugin:
    key: str | None = None
    enabled: bool = False
    target: PluginTarget | None = None
    has_run: bool = False

    def __init__(self, silent=False, verbose=False, debug=False) -> None:
        self.silent = silent
        self.debug = debug
        self.verbose = verbose

    def load(self, config: ConfigBox, env: dict[str, Any]) -> dict[str, str] | None:
        raise NotImplementedError("You must override the load method.")

    def prompt(self, msg: str) -> str:
        "Prompt the user with a y/n question."

        prompt: str = f"[bold]?[/] [bold blue]plugin:{self.key}[/] -> [bold]{msg}[/]"
        return rich.prompt.Prompt.ask(prompt)


# ==============================================================================


def load_plugin(plugin: BasePlugin, project_config: dict[str, Any], process_env: dict) -> None:
    plugin_config: ConfigBox | None = project_config.get(f"plugins.{plugin.key}")

    if not plugin_config or getattr(plugin, "has_run", False):
        if not plugin.silent:
            console.print(f"{Style.SKIP_LOAD}plugin [cyan]{plugin.key}[/] is already loaded")
        return

    for k, v in plugin_config.items():
        plugin_config[k] = realize(v, workdir=Path("."))

    if "tmp" not in plugin_config:
        plugin_config["tmp"] = project_config.get("tmp", "/tmp")

    data = plugin.load(config=plugin_config, env=process_env)

    if data and plugin.target is not None:
        if plugin.target == PluginTarget.ENV:
            process_env.update(data)
        elif plugin.target == PluginTarget.CONF:
            project_config.update(data)

    plugin.has_run = True

    if not plugin.silent:
        console.print(f"{Style.FINISH_LOAD}plugin: [cyan]{plugin.key}[/]")


# ==============================================================================


def load_plugins(
    project_config: ConfigBox,
    process_env: dict,
    enabled: dict[str, bool],  # passed from cli
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, BasePlugin]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_bin() / "plugins"
    plugin: BasePlugin
    plugins: dict[str, BasePlugin] = {}

    for mod in plugin_dir.glob("mod_*.py"):
        module: ModuleType = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[mod.stem] = module.Plugin(
            silent=project_config.get(f"plugins.{module.Plugin.key}.silent", silent),
            verbose=project_config.get(f"plugins.{module.Plugin.key}.verbose", verbose),
            debug=project_config.get(f"plugins.{module.Plugin.key}.debug", debug),
        )

    for plugin in plugins.values():
        if not (
            plugin.key
            and (plugin_config := project_config.get(f"plugins.{plugin.key}"))
            and (plugin_config.get("always", True) or enabled.get(plugin.key, False))
        ):
            continue

        load_plugin(plugin, project_config=project_config, process_env=process_env)

    return plugins


# ==============================================================================


def list_plugins() -> None:
    plugins_dir: Path = get_program_bin() / "plugins"

    for mod in plugins_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        if not module.plugin.enabled:
            continue
        doc: str = (module.__doc__ or "No description available.").strip("\n")
        console.print(f"\n[bold white]:black_circle:[/][bold yellow]{mod.stem}[/] {doc}")

    console.print()
