"""
Check for updates to adhd.

Queries Github repository for a new release of adhd, and notifies user.
"""

example = """
plugins:
  adhd:
    autoload: true
"""

required_modules: dict[str, str] = {
    "git": "GitPython",
    "github": "PyGithub",
    "semver": "semver",
}
required_binaries: list[str] = []

import sys
from pathlib import Path

from lib.boot import missing_modules
from lib.util import ConfigBox, Style, console, get_program_bin
from plugins import BasePlugin, MetadataType

missing: list[str]

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]adhd[/] updater disabled, missing modules: {', '.join(missing)}\n")
else:
    from github import Github, Repository
    from git import Repo  # type: ignore
    import semver

REPO = "cwells/adhd"

# ==============================================================================


class Plugin(BasePlugin):
    "Check Github for updates to [bold cyan]adhd[/]."

    key: str = "adhd"
    enabled: bool = not (missing)
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox, verbose: bool = False) -> MetadataType:
        "Check Github for new release tag for adhd."

        if not self.enabled or Github is None:
            self.print("support is disabled.", Style.ERROR)
            sys.exit(1)

        repo_path: Path = get_program_bin().parent
        local_tag: str = self.get_local_tag(repo_path)
        remote_tag: str = self.get_remote_tag()

        if semver.compare(remote_tag, local_tag) > 0:
            self.print(
                f"An update to [bold cyan]adhd[/] is available ({local_tag} -> {remote_tag}). "
                f"Run [bold white]git pull[/] from [bold blue]{repo_path}[/].\n"
            )

        return self.metadata

    def get_local_tag(self, repo_path: Path) -> str:
        repo: Repo = Repo(repo_path)
        tags: list[str] = sorted(t.name for t in repo.tags)
        latest_tag: str = tags[-1]

        return latest_tag

    def get_remote_tag(self) -> str:
        gh: GitHub = Github()  # type: ignore
        repo: Repository = gh.get_repo(REPO)
        tags: list[str] = sorted(t.name for t in repo.get_tags())
        latest_tag: str = tags[-1]

        return latest_tag
