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


def load_plugin(
    plugin: Plugin,
    project_config: dict[str, Any],
    process_env: dict,
    verbose: bool = False,
) -> None:
    plugin_config: dict[str, Any] | None = project_config.get(f"plugins.{plugin.key}")

    if not plugin_config:
        return

    plugin_config["tmp"] = project_config.get("tmp", "/tmp")
    data = plugin.load(config=plugin_config, env=process_env)

    if plugin.target == PluginTarget.ENV:
        process_env.update(data)
    elif plugin.target == PluginTarget.CONF:
        project_config.update(data)


def load_plugins(
    project_config: dict[str, Any],
    process_env: dict,
    enabled: dict[str, bool],
    verbose: bool = False,
) -> dict[str, Plugin]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_home() / "bin/plugins"
    plugin_name: str
    plugin: Plugin
    plugins: dict[str, Plugin] = {}

    for mod in plugin_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[(mod.stem)] = cast(Plugin, module)

    for plugin_name, plugin in plugins.items():
        if not (
            enabled.get(plugin.key, True)
            and plugin.key
            and (plugin_config := project_config.get(f"plugins.{plugin.key}"))
            and plugin_config.get("always", True)
        ):
            continue

        if verbose:
            console.print(f"{Style.START_LOAD}plugin {plugin_name}")

        load_plugin(
            plugin,
            project_config=project_config,
            process_env=process_env,
        )

        if verbose:
            console.print(f"{Style.FINISH_LOAD}plugin {plugin_name}")

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
