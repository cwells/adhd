import importlib
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from lib.util import Style, console, get_program_home


# ==============================================================================


class PluginTarget(Enum):
    "Plugins can update either environment or configuration."

    ENV = "env"
    CONF = "conf"


class Plugin(ModuleType):
    key: str
    load: Callable
    has_run: bool = False


# ==============================================================================


def load_plugin(
    plugin: Plugin,
    project_config: dict[str, Any],
    process_env: dict,
    verbose: bool = False,
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
    verbose: bool = False,
) -> dict[str, Plugin]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_home() / "bin/plugins"
    plugin: Plugin
    plugins: dict[str, Plugin] = {}

    for mod in plugin_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[(mod.stem)] = cast(Plugin, module)

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
            verbose=verbose,
        )

    return plugins


# ==============================================================================


def list_plugins() -> None:
    plugins_dir: Path = get_program_home() / "bin/plugins"

    for mod in plugins_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        if module.key is None:
            continue
        doc: str = (module.__doc__ or "No description available.").strip("\n")
        console.print(f"\n[bold white]:black_circle:[/][bold yellow]{mod.stem}[/] {doc}")

    console.print()
