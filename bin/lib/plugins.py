import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from lib.util import Style, console


# ==============================================================================


class Plugin(ModuleType):
    key: str
    load: Callable


def load_plugins(
    project_config: dict[str, Any],
    enabled: dict[str, bool],
    process_env: dict,
    verbose: bool = False,
) -> dict[str, str]:
    plugin_name: str
    plugin: Plugin
    env: dict = {}

    plugins: dict[str, Plugin] = {}
    for mod in Path("bin/plugins/").glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[(mod.stem)] = cast(Plugin, module)

    for plugin_name, plugin in plugins.items():
        if (
            enabled.get(plugin.key, True)
            and plugin.key
            and (config := project_config.get(f"plugins.{plugin.key}"))
        ):
            if verbose:
                console.print(f"{Style.START_LOAD}plugin {plugin_name}")

            env.update(plugin.load(config=config, env=process_env))
            if verbose:
                console.print(f"{Style.FINISH_LOAD}plugin {plugin_name}")
    return env


# ==============================================================================


def list_plugins() -> None:
    for mod in Path("bin/plugins/").glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        console.print(f"\n[bold white]:black_circle:[/][bold yellow]{mod.stem}")
        if module.__doc__:
            console.print(module.__doc__.strip())
    console.print()
