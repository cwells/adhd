#!/usr/bin/env python

#
# Add the following to your ~/.bashrc:
#
#     complete -C ~/.adhd/bin/completion.py adhd
#
# or, if you've symlinked to a different name, say "~/.local/bin/foo",
#
#     complete -C ~/.adhd/bin/completion.py foo
#

import json
import sys
from pathlib import Path
from typing import Any

import ruamel.yaml as yaml
from lib.loader import get_loader


def get_project_data(project: Path) -> Any:
    "returns cached project data unless project yaml is newer than cache."

    cache: Path = Path(f"{project.parent}") / Path(f".{project.stem}.completions")
    projects: dict[str, list[str]] = {}

    if not cache.exists() or project.stat().st_mtime > cache.stat().st_mtime:
        _conf: dict[str, Any] = yaml.load(open(project, "r"), Loader=get_loader())
        projects[project.stem] = list(str(key) for key in _conf["jobs"])
        cache.open("w").write(json.dumps(projects))
        return projects

    return json.loads(cache.open("r").read())


def get_project_paths(project_home: Path) -> list[Path]:
    "return list of Paths to project files, e.g. ~/.adhd/projects/*.yaml"

    project_dir: Path = project_home / "projects"

    return list(project_dir.glob("*.yaml"))


def load_projects(home: str) -> dict[str, list[str]]:
    project_home = Path(f"~/.{home}").expanduser().resolve()
    projects: dict[str, list[str]] = {}

    for project in get_project_paths(project_home):
        try:
            projects = get_project_data(project)
        except Exception as e:
            continue

    return projects


def completion_hook(cmd: str, curr_word: str, prev_word: str) -> list[str]:
    projects: dict[str, list[str]] = load_projects(home=cmd)

    if prev_word in projects:
        jobs = projects[prev_word]
        return [j for j in jobs if j.startswith(curr_word)]

    elif prev_word == cmd:
        return [p for p in projects if p.startswith(curr_word)]

    return []


def main():
    results = completion_hook(*sys.argv[1:])
    if len(results):
        print("\n".join(results))


if __name__ == "__main__":
    main()
