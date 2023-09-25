import sys
from pathlib import Path
from typing import Any, Generator

from .plugins import Plugin, load_plugin
from .util import ConfigBox, LazyValue, Style, console, get_resolved_path, get_sorted_deps, resolve_dependencies

# ==============================================================================


def get_job(
    command: str,
    job_config: ConfigBox,
    project_config: ConfigBox,
    process_env: dict[str, str],
) -> ConfigBox:
    "Build a job structure from configuration."

    env: dict[str, Any] = {**process_env, **job_config.get("env", {})}

    def _eval(v: Any, *args, **kwargs) -> Any:
        if not v:
            return v

        if isinstance(v, dict):
            for _k, _v in v.items():
                v[_k] = _eval(_v)
            return v
        elif isinstance(v, (list, tuple)):
            v = [_eval(i) for i in v]
            return v

        return v(*args, **kwargs) if callable(v) else v

    home: str | LazyValue = job_config.get("home") or project_config.get("home", ".")
    tmp: str | LazyValue = job_config.get("tmp") or project_config.get("tmp", "./tmp")
    workdir: Path = get_resolved_path(home, env=env)
    tmpdir: Path = get_resolved_path(tmp, env=env)
    cmd: Any = _eval(job_config.get("run", []), workdir=workdir, env=env)
    tasks: list = cmd if isinstance(cmd, list) else [cmd]
    task_env: dict[str, str] = resolve_dependencies(job_config.get("env", ConfigBox()), workdir)
    job: ConfigBox = ConfigBox(
        {
            "name": command,
            "tasks": tasks,
            "env": {**env, **task_env},
            "workdir": str(workdir),
            "tmp": str(tmpdir),
            "open": _eval(job_config.get("open"), workdir=workdir, env=env),
            "skip": _eval(job_config.get("skip", lambda *_, **__: False), workdir=workdir, env=env),
            "capture": _eval(job_config.get("capture", False), workdir=workdir, env=env),
            "interactive": _eval(job_config.get("interactive", False), workdir=workdir, env=env),
            "confirm": _eval(job_config.get("confirm"), workdir=workdir, env=env),
            "silent": job_config.get("silent"),
            "sleep": job_config.get("sleep", 0),
            "help": job_config.get("help", "No help available."),
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
    plugins: dict[str, Plugin],
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
        # TODO: use rest of cli as job arguments?
        for dep in get_sorted_deps(_cmd, jobs, workdir=workdir, env=process_env):
            job_config: ConfigBox = jobs.get(dep, {})
            if dep.startswith("plugin:"):
                _, _plugin_name = dep.split(":", 1)
                _plugin_key = f"mod_{_plugin_name}"
                _plugin: Plugin | None = plugins.get(_plugin_key)
                if _plugin:
                    load_plugin(_plugin, project_config, process_env, verbose=verbose)
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
            "silent": False,
            "skip": False,
            "help": "I can't explain this.",
        }
