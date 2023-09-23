import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from lib.util import Style, console, get_program_home


# ==============================================================================


class Plugin(ModuleType):
    key: str
    load: Callable


def load_plugins(
    project_config: dict[str, Any],
    enabled: dict[str, bool],
    process_env: dict,
    verbose: bool = False,
) -> tuple[dict[str, str], ...]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_home() / "bin/plugins"
    plugin_name: str
    plugin: Plugin
    plugins: dict[str, Plugin] = {}
    env: dict = {}  # target == "env"
    conf: dict = {}  # target == "conf"

    for mod in plugin_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[(mod.stem)] = cast(Plugin, module)

    for plugin_name, plugin in plugins.items():
        if (
            enabled.get(plugin.key, True)
            and plugin.key
            and (plugin_config := project_config.get(f"plugins.{plugin.key}"))
        ):
            if verbose:
                console.print(f"{Style.START_LOAD}plugin {plugin_name}")
            data = plugin.load(config=plugin_config, env=process_env)
            if plugin.target == "env":
                env.update(data)
            elif plugin.target == "conf":
                conf.update(data)

            if verbose:
                console.print(f"{Style.FINISH_LOAD}plugin {plugin_name}")

    return conf, env


# ==============================================================================


def list_plugins() -> None:
    plugins_dir: Path = get_program_home() / "bin/plugins"

    for mod in plugins_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        console.print(f"\n[bold white]:black_circle:[/][bold yellow]{mod.stem}")
        if module.__doc__:
            console.print(module.__doc__.strip())
    console.print()
