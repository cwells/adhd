import re
import sys
from pathlib import Path
from typing import Any, Generator

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


def get_jobs(
    command: list[str] | tuple[str, ...],
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

    if not command:
        console.print(f"No command given.")
        sys.exit(1)

    if (_cmd := command[0]) in jobs:  # pre-defined jobs
        # TODO: use rest of cli as job arguments or sequential jobs?
        for dep in get_sorted_deps(_cmd, jobs, workdir=workdir, env=process_env):
            job_config: ConfigBox = jobs.get(dep, {})

            if match := re.match(r"(?P<action>[^:]+):(?P<plugin>[^.]+)(\.(?P<method>.+))?", dep):
                callinfo: dict[str, str] = match.groupdict()
                plugin_name = callinfo["plugin"]
                plugin_key = f"mod_{plugin_name}"
                plugin: BasePlugin | None = plugins.get(plugin_key)
                if plugin:
                    if callinfo["action"] == "plugin":
                        if not plugin.has_run:
                            load_plugin(plugin, project_config, process_env)
                        if method := callinfo.get("method"):
                            call_plugin_method(plugin, method, project_config, process_env)
                    elif callinfo["action"] == "unplug":
                        unload_plugin(plugin, project_config, process_env)
                continue

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
