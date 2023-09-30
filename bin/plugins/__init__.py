"""
Plugins can do pretty much anything, but they can only directly affect two aspects
of `adhd`: configuration and environment. This is done by way of their return
value, which is autoload a dictionary and will be merged with the relevant part
of the execution environment.

Plugins are only run once, either at boot time (if `autoload: true` is specified
in plugin configuration), or on-demand, if they are specified as a dependency
for a job (e.g. `after: plugin:python`).
"""

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import rich.prompt
import rich.style
from rich.syntax import Syntax
from rich.table import Table

from lib.util import ConfigBox, Style, console, get_program_bin, realize

# ==============================================================================

MetadataType = dict[Literal["conf", "env", "vars"], dict[str, Any]]


class BasePlugin:
    key: str | None = None
    enabled: bool = False
    metadata: MetadataType
    has_run: bool = False

    def __init__(self, silent=False, verbose=False, debug=False) -> None:
        self.silent = silent
        self.debug = debug
        self.verbose = verbose
        self.metadata = {"conf": {}, "env": {}, "vars": {}}

    def load(self, config: ConfigBox, env: dict[str, Any]) -> MetadataType:
        raise NotImplementedError("You must override the load method.")

    def unload(self, config: ConfigBox, env: dict[str, Any]) -> None:
        console.print(f"Plugin [bold blue]{self.key}[/] does not support unloading.")

    def prompt(self, msg: str) -> str:
        "Prompt the user with a y/n question."

        prompt: str = f"[bold]?[/] [bold blue]plugin:{self.key}[/] -> [bold]{msg}[/]"
        return rich.prompt.Prompt.ask(prompt)


# ==============================================================================


def load_plugin(
    plugin: BasePlugin,
    project_config: ConfigBox,
    process_env: dict,
) -> None:
    "Load a plugin, if enabled."

    plugin_config: ConfigBox | None = project_config.get(f"plugins.{plugin.key}")

    if not plugin_config or getattr(plugin, "has_run", False):
        if not plugin.silent:
            console.print(f"{Style.SKIP_LOAD}plugin [cyan]{plugin.key}[/] is already loaded")
        return

    if "tmp" not in plugin_config:
        plugin_config["tmp"] = project_config.get("tmp", "/tmp")

    for k, v in plugin_config.items():
        plugin_config[k] = realize(v, workdir=Path("."))

    data = plugin.load(config=plugin_config, env=process_env)

    if data:  # plugins can update runtime environment
        process_env.update(data.get("env", {}))
        project_config.update(data.get("conf", {}))
        project_config.plugins[plugin.key].setdefault("__vars__", {})
        project_config.plugins[plugin.key]["__vars__"].update(data.get("vars", {}))

    plugin.has_run = True

    if not plugin.silent:
        console.print(f"{Style.FINISH_LOAD}plugin: [cyan]{plugin.key}[/]")


# ==============================================================================


def unload_plugin(plugin: BasePlugin, project_config: ConfigBox, process_env: dict[str, Any]) -> None:
    "Unload plugin, if supported."

    plugin.unload(project_config, process_env)

    if env := plugin.metadata.get("env"):
        for k in env:
            process_env.pop(k, None)

    plugin.has_run = False

    if not plugin.silent:
        console.print(f"{Style.FINISH_UNLOAD}plugin: [cyan]{plugin.key}[/]")


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
            and (plugin_config.get("autoload", True) or enabled.get(plugin.key, False))
        ):
            continue

        load_plugin(plugin, project_config=project_config, process_env=process_env)

    return plugins


# ==============================================================================


def list_plugins() -> None:
    plugins_dir: Path = get_program_bin() / "plugins"
    table: Table = Table(
        show_header=False, padding=2, highlight=True, border_style=rich.style.Style(color="grey15")
    )
    row_styles: list[str] = ["grey7", "grey15"]

    table.add_column("Description", justify="left")
    table.add_column("Example", justify="left")

    idx: int = 0
    for mod in plugins_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{mod.stem}")
        if not module.Plugin.enabled:
            continue

        doc: str = (module.__doc__ or "No description available.").strip("\n")
        row: list[str] = [
            f"[bold yellow]{mod.stem}[/]: {doc}\n",
        ]

        required_modules: str = "[/], [cyan]".join(module.required_modules.values())
        required_binaries: str = "[/], [cyan]".join(module.required_binaries)

        if required_modules or required_binaries:
            row.append("[bold white]Requirements:[/]")

        if required_modules:
            row.append(f":white_circle:modules: [cyan]{required_modules}[/]")
        if required_binaries:
            row.append(f":white_circle:programs: [cyan]{required_binaries}[/]")

        example: Syntax = Syntax(
            getattr(module, "example", "").strip(),
            "yaml",
            background_color=row_styles[idx % 2],
        )

        table.add_row("\n".join(row), example, style=f"white on {row_styles[idx % 2]}")

        idx += 1

    # with console.pager():
    console.print(table)
