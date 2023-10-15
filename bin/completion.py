#!/usr/bin/env python3
import sys
from pathlib import Path

import ruamel.yaml as yaml
from lib.loader import get_loader


def get_project_paths(project_home: Path) -> list[Path]:
    "return list of Paths to project files, e.g. ~/.adhd/projects/*.yaml"

    project_dir: Path = project_home / "projects"

    return list(project_dir.glob("*.yaml"))


def load_projects(home: str) -> dict[str, list[str]]:
    projects: dict[str, list[str]] = {}
    project_home = Path(f"~/.{home}").expanduser().resolve()

    for project in get_project_paths(project_home):
        try:
            _conf = yaml.load(open(project, "r"), Loader=get_loader())
        except Exception as e:
            continue

        projects[project.stem] = list(str(key) for key in _conf["jobs"])

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
