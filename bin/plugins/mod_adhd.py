"""
Check for updates to [cyan]adhd[/].

Queries Github repository for a new release of [cyan]adhd[/] and notifies user.

By default, the location of the [cyan]adhd[/] executable is presumed to be in the local repository.

Optionally, you may override the [cyan]local[/] and [cyan]remote[/] repositories.

If remote repo is private, you may provide an optional GitHub [cyan]token[/].
"""

example = """
plugins:
  adhd-update:
    autoload: true
    remote: cwells/adhd
    local: ~/.adhd
    token: fake_token_q4r1fn4iqf432099lol053tqfqsdfAAfaBa
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

REMOTE_REPO = "cwells/adhd"
LOCAL_REPO = get_program_bin().parent


# ==============================================================================


class Plugin(BasePlugin):
    "Check Github for updates to [bold cyan]adhd[/]."

    key: str = "adhd-update"
    enabled: bool = not missing
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox, verbose: bool = False) -> MetadataType:
        "Check Github for new release tag for adhd."

        if not self.enabled or Github is None:
            self.print("support is disabled.", Style.ERROR)
            sys.exit(1)

        remote: str = config.get("remote", REMOTE_REPO)
        local: str = config.get("local", LOCAL_REPO)
        token: str = config.get("token")

        local_tag: str | None = self.get_local_tag(local)
        remote_tag: str | None = self.get_remote_tag(remote, token=token)

        if not remote_tag:
            return self.metadata

        if not local_tag or semver.compare(remote_tag, local_tag) > 0:
            self.print(
                f"An update to [bold cyan]adhd[/] is available ({local_tag} -> {remote_tag}). "
                f"Run [bold white]git pull[/] from [bold blue]{local}[/].\n"
            )

        return self.metadata

    def get_local_tag(self, local: str) -> str | None:
        repo: Repo = Repo(Path(local).expanduser().resolve())
        tags: list[str] = sorted(t.name for t in repo.tags)
        return tags[-1] if tags else None

    def get_remote_tag(self, remote: str, token: str | None) -> str | None:
        gh: GitHub = Github(token)  # type: ignore
        repo: Repository = gh.get_repo(remote)  # type: ignore
        tags: list[str] = sorted(t.name for t in repo.get_tags())  # type: ignore
        return tags[-1] if tags else None
