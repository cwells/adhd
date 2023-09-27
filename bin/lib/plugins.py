import importlib
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import rich.prompt

from .util import ConfigBox, Style, console, get_program_bin

# ==============================================================================


class PluginTarget(Enum):
    "Plugins can update either environment or configuration."

    ENV = "env"
    CONF = "conf"


class PluginModule(ModuleType):
    key: str
    load: Callable
    has_run: bool = False


# ==============================================================================


def load_plugin(
    plugin: PluginModule,
    project_config: dict[str, Any],
    process_env: dict,
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    plugin_config: dict[str, Any] | None = project_config.get(f"plugins.{plugin.key}")

    if not plugin_config or getattr(plugin, "has_run", False):
        if verbose:
            console.print(f"{Style.SKIP_LOAD}plugin [cyan]{plugin.key}[/] is already loaded")
        return

    plugin_config["tmp"] = project_config.get("tmp", "/tmp")
    data = plugin.load(config=plugin_config, env=process_env)

    if plugin.target == PluginTarget.ENV:
        process_env.update(data)
    elif plugin.target == PluginTarget.CONF:
        project_config.update(data)

    plugin.has_run = True

    if verbose:
        console.print(f"{Style.FINISH_LOAD}plugin: [cyan]{plugin.key}[/]")


# ==============================================================================


def load_plugins(
    project_config: dict[str, Any],
    process_env: dict,
    enabled: dict[str, bool],  # passed from cli
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> dict[str, PluginModule]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_bin() / "plugins"
    plugin: PluginModule
    plugins: dict[str, PluginModule] = {}

    for mod in plugin_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[(mod.stem)] = module.Plugin(silent=silent, verbose=verbose, debug=debug)

    for plugin in plugins.values():
        if not (
            plugin.key
            and (plugin_config := project_config.get(f"plugins.{plugin.key}"))
            and (plugin_config.get("always", True) or enabled.get(plugin.key, False))
        ):
            continue

        load_plugin(
            plugin,
            project_config=project_config,
            process_env=process_env,
            silent=silent,
            verbose=verbose,
            debug=debug,
        )

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


# ==============================================================================


class BasePlugin:
    key: str | None = None
    enabled: bool = False
    target: PluginTarget | None = None
    has_run: bool = False

    def __init__(self, silent=False, verbose=False, debug=False) -> None:
        self.silent = silent
        self.debug = debug
        self.verbose = verbose

    def load(
        self,
        config: ConfigBox,
        env: dict[str, Any],
        verbose: bool = False,
    ) -> dict[str, str] | None:
        raise NotImplementedError("You must override the load method.")

    def prompt(self, msg: str) -> str:
        "Prompt the user with a y/n question."

        prompt: str = f"[bold]?[/] [bold blue]plugin:{self.key}[/] -> [bold]{msg}[/]"
        return rich.prompt.Prompt.ask(prompt)
