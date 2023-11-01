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
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Literal

import rich.prompt
import rich.style
from rich.syntax import Syntax
from rich.table import Table

from lib.util import ConfigBox, Style, console, get_program_bin, realize, _exit

# ==============================================================================

MetadataType = dict[Literal["conf", "env", "vars"], dict[str, Any]]


class BasePlugin:
    "Base class for plugins."

    key: str | None = None
    enabled: bool = False
    metadata: MetadataType
    has_run: bool = False
    events: ConfigBox

    def __init__(self, verbose=False, debug=False) -> None:
        self.debug = debug
        self.verbose = verbose
        self.metadata = {"conf": {}, "env": {}, "vars": {}}
        self.events = ConfigBox(
            {
                "load": None,
                "unload": None,
                "exit": None,
            }
        )
        for k in self.events:
            self.events[k] = []

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        raise NotImplementedError("You must override the load method.")

    def unload(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Optional method to unload the plugin and cleanup."
        console.print(f"Plugin [bold blue]{self.key}[/] does not support unloading.")
        return self.metadata

    def prompt(self, msg: str) -> str:
        "Prompt the user with a y/n question."
        prompt: str = f"[bold]?[/] [bold blue]plugin:{self.key}[/] -> [bold]{msg}[/]"
        return rich.prompt.Prompt.ask(prompt)

    def print(self, msg: str, style: Style = Style.INFO) -> None:
        "Output prefixed with plugin identifier."
        console.print(f"  {style}{msg}")

    def print_success(self, msg: str) -> None:
        console.print(f"[cyan]{self.key}[/] {Style.SUCCESS}{msg}[/]")

    def print_error(self, msg: str) -> None:
        console.print(f"[cyan]{self.key}[/] {Style.ERROR}{msg}[/]")


# ==============================================================================


def load_plugin(
    plugin: BasePlugin,
    project_config: ConfigBox,
    process_env: ConfigBox,
    explain: bool = False,
) -> None:
    "Load a plugin, if enabled."

    if not project_config.get(f"plugins.{plugin.key}"):
        return

    plugin_name: str = f"plugin:{plugin.key}"
    pad: int = 20

    if plugin.has_run:
        return

    if explain:
        console.print(f"{Style.PLUGIN_INFO}[cyan]{plugin_name:<{pad}}[/] {plugin.__doc__}")
        return

    console.print(f"{Style.PLUGIN_LOAD}[cyan]{plugin_name:<{pad}}[/] [dim]{plugin.__doc__}")

    if "tmp" not in project_config.plugins[plugin.key]:
        project_config.plugins[plugin.key].tmp = project_config.get("tmp", "/tmp")

    for k, v in project_config.plugins[plugin.key].items():
        project_config.plugins[plugin.key][k] = realize(v, workdir=Path("."))

    data = plugin.load(config=project_config, env=process_env)

    if data:  # plugins can update runtime environment
        process_env.update(data.get("env", {}) | process_env)
        project_config.update(data.get("conf", {}))
        project_config.plugins[plugin.key].setdefault("__vars__", {})
        project_config.plugins[plugin.key]["__vars__"].update(data.get("vars", {}))

    for fn in plugin.events.load:
        fn()

    plugin.has_run = True


# ==============================================================================


def unload_plugin(
    plugin: BasePlugin,
    project_config: ConfigBox,
    process_env: ConfigBox,
    explain: bool = False,
) -> None:
    "Unload plugin, if supported."

    plugin_config: ConfigBox | None = project_config.get(f"plugins.{plugin.key}")
    pad: int = 20

    if not plugin_config:
        return

    if "tmp" not in plugin_config:
        plugin_config["tmp"] = project_config.get("tmp", "/tmp")

    for k, v in plugin_config.items():
        plugin_config[k] = realize(v, workdir=Path("."))

    if explain:
        console.print(f"{Style.PLUGIN_INFO}[cyan]unplug:{plugin.key:<{pad}}[/] {plugin.unload.__doc__}")
        return

    plugin.unload(config=plugin_config, env=process_env)

    if env := plugin.metadata.get("env"):
        for k, v in env.items():
            if v is None:
                process_env.pop(k, None)
            else:
                process_env.env[k] = v

    for fn in plugin.events.unload:
        fn()

    plugin.has_run = False

    plugin_name: str = f"unplug:{plugin.key}"
    console.print(f"{Style.PLUGIN_UNLOAD}[cyan]{plugin_name:<{pad}}[/] [dim]{plugin.unload.__doc__}")


# ==============================================================================


def load_plugins(
    project_config: ConfigBox,
    process_env: ConfigBox,
    enabled: dict[str, bool],  # passed from cli
    verbose: bool = False,
    debug: bool = False,
    explain: bool = False,
) -> dict[str, BasePlugin]:
    "Locate plugins, import them, and run plugin.load() for each."

    plugin_dir: Path = get_program_bin() / "plugins"
    plugin: BasePlugin
    plugins: dict[str, BasePlugin] = {}

    for mod in plugin_dir.glob("mod_*.py"):
        module: ModuleType = importlib.import_module(f"plugins.{mod.stem}")
        importlib.reload(module)
        plugins[mod.stem] = module.Plugin(
            verbose=verbose or project_config.get(f"plugins.{module.Plugin.key}.verbose", False),
            debug=debug or project_config.get(f"plugins.{module.Plugin.key}.debug", False),
        )

    for plugin in plugins.values():
        if not (
            plugin.key
            and (plugin_config := project_config.get(f"plugins.{plugin.key}"))
            and (plugin_config.get("autoload", True) or enabled.get(plugin.key, False))
        ):
            continue

        if not plugin.has_run:
            load_plugin(plugin, project_config=project_config, process_env=process_env)

    return plugins


# ==============================================================================


def unload_plugins(plugins: dict[str, BasePlugin], project_config: ConfigBox, process_env: ConfigBox):
    for key, plugin in plugins.items():
        if plugin.has_run:
            unload_plugin(plugin, project_config, process_env)


# ==============================================================================


def explain_plugin(plugin: BasePlugin, project_config: ConfigBox, process_env: ConfigBox) -> None:
    help: str = plugin.__doc__.split("\n")[0] if plugin.__doc__ else "No help available."
    console.print(f"[cyan]{plugin.key}[/] {help}")


# ==============================================================================


def notify_plugins(
    event: str,
    plugins: dict[str, BasePlugin],
    project_config: ConfigBox,
    process_env: ConfigBox,
) -> None:
    for key, plugin in plugins.items():
        if plugin.has_run:
            for fn in plugin.events.get(event, []):
                fn()


# ==============================================================================


def print_plugin_help(pager: str | bool = False, verbose=False) -> None:
    plugins_dir: Path = get_program_bin() / "plugins"
    plugins: dict[str, BasePlugin] = {}

    for module_file in plugins_dir.glob("mod_*.py"):
        module = importlib.import_module(f"plugins.{module_file.stem}")
        if not module.Plugin.enabled:
            continue
        plugins[module_file.stem] = module  # type: ignore

    if verbose:
        return print_plugin_help_verbose(plugins, pager=pager)

    width: int = max(len(p) for p in plugins) + 22

    console.print()
    for key, plugin in sorted(plugins.items()):
        doc: str = (plugin.__doc__ or "No description available.").strip("\n").split("\n")[0]
        console.print(
            f" :white_circle:{f'[bold cyan]{key}[/] [dim]':.<{width}}[/] {doc}",
            highlight=False,
        )
    console.print()


def print_plugin_help_verbose(plugins: dict[str, BasePlugin], pager: str | bool = False) -> None:
    table: Table = Table(
        show_header=False,
        padding=2,
        highlight=True,
        border_style=rich.style.Style(color="grey15"),
    )
    row_styles: list[str] = ["grey7", "grey15"]

    table.add_column("Description", justify="left")
    table.add_column("Example", justify="left")

    idx: int = 0
    for plugin, module in sorted(plugins.items()):
        doc: str = (module.__doc__ or "No description available.").strip("\n")
        row: list[str] = [
            f"[bold]:gear: [/][bold cyan][u]{module.Plugin.key}[/u][/] {doc}\n",  # type: ignore
        ]

        required_modules: str = "[/], [cyan]".join(module.required_modules.values())  # type: ignore
        required_binaries: str = "[/], [cyan]".join(module.required_binaries)  # type: ignore

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

    if not pager:
        console.print(table)
    else:
        with console.pager(styles=pager == "color"):
            console.print(table)


# ==============================================================================


def public(autoload: bool = False):
    "Decorator to mark a plugin method as public. If autoload is true, load plugin first."

    def decorator(method: Callable) -> Callable:
        setattr(method, "is_public", True)
        setattr(method, "autoload", autoload)
        return method

    return decorator


# ==============================================================================


def call_plugin_method(
    plugin: BasePlugin,
    method: str,
    args: tuple[str, ...],
    project_config: ConfigBox,
    process_env: ConfigBox,
    explain: bool = False,
) -> Any:
    "If plugin has method and it's public, call it."

    _method: Callable | None

    if not plugin.key or not plugin.enabled:
        raise NotImplementedError(f"Plugin '{plugin.key}' is either unknown or disabled ({plugin.enabled})")

    if _method := getattr(plugin, method):
        if getattr(_method, "is_public", False):
            if explain:
                name: str = f"plugin:{plugin.key}.{method}"
                console.print(f"{Style.PLUGIN_INFO}[cyan]{name:<23}[/] {_method.__doc__}")
                return

            data = _method(args=args, config=project_config["plugins"][plugin.key], env=process_env)
            if data:  # plugins can update runtime environment
                process_env.update(data.get("env", {}))
                project_config.update(data.get("conf", {}))
                project_config.plugins[plugin.key].setdefault("__vars__", {})
                project_config.plugins[plugin.key]["__vars__"].update(data.get("vars", {}))
            return

    raise NotImplementedError(f"Unknown plugin function '{plugin.key}.{method}'")


# ==============================================================================

plugin_regex = re.compile(r"(?P<action>[^:]+):(?P<plugin>[^.]+)(\.(?P<method>.+))?")


def get_plugin_cmd(cmd: str) -> dict | None:
    if match := plugin_regex.match(cmd):
        return match.groupdict()
    return None


def load_or_unload_plugin(
    command: tuple[str, ...],
    plugins: dict[str, BasePlugin],
    project_config: ConfigBox,
    process_env: ConfigBox,
    explain: bool = False,
) -> BasePlugin | None:
    "If cmd is a plugin, attempt to load/unload or call one of its methods."

    plugin: BasePlugin | None = None
    cmd: str = command[0]
    args: tuple[str, ...] = command[1:]

    if plugin_cmd := get_plugin_cmd(cmd):
        plugin_name = plugin_cmd["plugin"]
        if plugin := plugins.get(f"mod_{plugin_name}"):
            if plugin_cmd["action"] == "plugin":
                if method := plugin_cmd.get("method"):
                    if (_method := getattr(plugin, method)) and getattr(_method, "is_public", False):
                        if getattr(_method, "autoload", False):
                            load_plugin(plugin, project_config, process_env, explain=explain)
                        try:
                            call_plugin_method(plugin, method, args, project_config, process_env, explain=explain)
                        except NotImplementedError as e:
                            _exit(e, 2)
                    else:
                        console.print(f"Unknown or private method: [bold red]{plugin_name}.{method}[/]")
                        sys.exit(2)
                else:
                    load_plugin(plugin, project_config, process_env, explain=explain)

            elif plugin_cmd["action"] == "unplug":
                unload_plugin(plugin, project_config, process_env, explain=explain)

    return plugin
