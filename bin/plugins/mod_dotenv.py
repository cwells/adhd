"""
[bold cyan]Import .env files.[/]

Import one or more .env files into the runtime environment.
"""

example = """
dotenv:
  autoload: true
  files:
  - !path [ ~/projects/.env ]
  - !path [ ~/projects/.dev.env ]
"""

required_modules: dict[str, str] = {"dotenv": "python-dotenv"}
required_binaries: list[str] = []

import sys
from pathlib import Path
from typing import Any

from lib.boot import missing_modules
from lib.util import ConfigBox, Style, check_permissions, console
from plugins import BasePlugin, MetadataType

missing: list[str]

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]dotenv[/] disabled, missing modules: {', '.join(missing)}\n")
    dotenv_values = None
else:
    from dotenv import dotenv_values


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "dotenv"
    enabled: bool = dotenv_values is not None
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, Any], verbose: bool = False) -> MetadataType:
        "Import .env files. The circle is complete."

        if not self.enabled:  # we were unable to import module
            console.print(f"{Style.ERROR}dotenv support is disabled. Please install python-dotenv package.")
            sys.exit(1)

        conf: ConfigBox = ConfigBox()
        files: list[str] = config.get("files", [])
        secure_paths: dict[Path, int] = {
            Path(f).expanduser().resolve(): 0o0600 for f in files
        }  # FIXME: too strict - should allow o+r ?

        if not check_permissions(secure_paths):
            sys.exit(2)

        _env: dict[str, str | None] | None

        for filename in files:
            path: Path = Path(filename).expanduser().resolve()
            if not path.exists():
                console.print(f"{Style.ERROR}No such .env file {path}")
                continue

            if _env := dotenv_values(dotenv_path=path):  # type: ignore
                conf.update(_env)
            if verbose:
                console.print(f"Imported environment from {filename}")

        self.metadata["conf"].update(conf)

        return self.metadata
