import re
import sys
from pathlib import Path
from typing import Any, Generator, Literal

import rich.prompt
from plugins import BasePlugin, call_plugin_method, load_plugin, unload_plugin

from .util import (
    ConfigBox,
    LazyValue,
    Style,
    console,
    get_resolved_path,
    get_sorted_deps,
    realize,
    resolve_dependencies,
)

# ==============================================================================


def get_job(
    command: tuple[str, ...] | list[str] | str,
    job_config: ConfigBox,
    project_config: ConfigBox,
    process_env: dict[str, str],
    informational: bool = False,  # don't _eval values that we don't need
) -> ConfigBox:
    "Build a job structure from configuration."

    env: dict[str, Any] = {**process_env, **job_config.get("env", {})}
    home: str | LazyValue = job_config.get("home") or project_config.get("home", ".")
    tmp: str | LazyValue = job_config.get("tmp") or project_config.get("tmp", "./tmp")
    workdir: Path = get_resolved_path(home, env=env)
    tmpdir: Path = get_resolved_path(tmp, env=env)
    cmd: Any = realize(job_config.get("run", []), workdir=workdir, env=env)
    tasks: list = cmd if isinstance(cmd, list) else [cmd]
    task_env: dict[str, str] = resolve_dependencies(job_config.get("env", ConfigBox()), workdir)
    after: list[str] = _after if isinstance((_after := job_config.get("after", [])), list) else [_after]

    job: ConfigBox = ConfigBox(
        {
            "env": {**env, **task_env},
            "help": realize(job_config.get("help", "No help available."), workdir=workdir, env=env),
            "name": command,
            "tasks": tasks,
            "tmp": str(tmpdir),
            "workdir": str(workdir),
            "after": after,
        }
    )

    if not informational:
        job.update(
            {
                "capture": realize(job_config.get("capture", False), workdir=workdir, env=env),
                "confirm": realize(job_config.get("confirm"), workdir=workdir, env=env),
                "interactive": realize(job_config.get("interactive", False), workdir=workdir, env=env),
                "open": realize(job_config.get("open"), workdir=workdir, env=env),
                "silent": realize(
                    job_config.get("silent", project_config.get("silent", False)), workdir=workdir, env=env
                ),
                "skip": realize(job_config.get("skip", lambda *_, **__: False), workdir=workdir, env=env),
                "sleep": int(realize(job_config.get("sleep", 0), workdir=workdir, env=env)),
            }
        )

    if not (job["tasks"] or job_config.get("after") or job_config.get("open")):
        console.print(f"{Style.ERROR}{command}: must have at least one command, dependency, or open directive.")
        sys.exit(1)

    return job


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
    process_env: dict[str, Any],
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> bool:
    "If cmd is a plugin, attempt to load/unload or call one of its methods."

    plugin: BasePlugin | None = None
    cmd: str = command[0]
    args: tuple[str, ...] = command[1:]

    if plugin_cmd := get_plugin_cmd(cmd):
        plugin_name = plugin_cmd["plugin"]
        if plugin := plugins.get(f"mod_{plugin_name}"):
            if plugin_cmd["action"] == "plugin":
                load_plugin(
                    plugin,
                    project_config,
                    process_env,
                    silent=silent,
                    verbose=verbose,
                    debug=debug,
                )
                if method := plugin_cmd.get("method"):
                    call_plugin_method(plugin, method, args, project_config, process_env)
            elif plugin_cmd["action"] == "unplug":
                unload_plugin(plugin, project_config, process_env)

    return bool(plugin)


def get_jobs(
    command: tuple[str, ...],
    project_config: ConfigBox,
    process_env: dict,
    plugins: dict[str, BasePlugin],
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> Generator:
    """
    Determine whether we're going to use a pre-defined job from configuration, or
    if we're console.print a cli command and generate a list of job structures with
    their associated env and other configuration.
    """

    home: str | LazyValue = project_config.get("home", ".")
    tmp: str | LazyValue = project_config.get("tmp", "./tmp")
    workdir: Path = Path(home(project_config["env"]) if isinstance(home, LazyValue) else home)
    tmpdir: Path = Path(tmp(project_config["env"]) if isinstance(tmp, LazyValue) else tmp)
    jobs: dict[str, Any] = project_config.get("jobs", {})

    _cmd: str = command[0]
    _args: tuple[str, ...] = command[1:]  # TODO: use these if they exist

    if not command:
        console.print(f"No command given.")
        sys.exit(1)

    if load_or_unload_plugin(command, plugins, project_config, process_env):
        pass

    elif _cmd in jobs:  # pre-defined jobs
        if confirm := jobs[_cmd].get("confirm"):
            _confirm = realize(confirm, workdir=workdir, env=process_env)
            if not rich.prompt.Confirm.ask(_confirm, default=False, console=console):
                if rich.prompt.Confirm.ask("Would you like to abort?", default=True, console=console):
                    raise SystemExit("Aborted by user request.\n")

        #  TODO: run skip test here to prevent deps from running?

        for dep in get_sorted_deps(_cmd, jobs, workdir=workdir, env=process_env):
            if load_or_unload_plugin(tuple(dep.split()), plugins, project_config, process_env):
                continue

            job_config: ConfigBox = jobs.get(dep, {})
            try:
                yield get_job(dep, job_config, project_config, process_env)
            except Exception as e:
                console.print(f"{Style.ERROR} job [bold cyan]{_cmd}[/] failed: [bold white]{e}[/]")
                if debug:
                    raise
                sys.exit(1)

    else:  # cli command
        cmd: str = " ".join(command)
        yield {
            "name": cmd,
            "env": process_env,
            "workdir": str(workdir),
            "tmp": str(tmpdir),
            "tasks": [cmd],
            "sleep": 0,
            "capture": False,
            "interactive": True,
            "silent": silent,
            "verbose": verbose,
            "debug": debug,
            "skip": False,
            "help": "I can't explain this.",
        }
