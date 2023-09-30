"""
[bold cyan]Include external YAML files.[/]

Note that inclusion happens relative to the document root, _not_ in-place within
the plugins section.

  include:
  - file1.yaml
  - !path [ "~", projects/file2.yaml ]
"""

from typing import Any

import yaml
from lib.plugins import BasePlugin, MetadataType
from lib.util import ConfigBox, console

# ==============================================================================


class Plugin(BasePlugin):
    key: str | None = None
    enabled: bool = False
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, Any], verbose: bool = False) -> MetadataType:
        "Include YAML files"

        conf: ConfigBox = ConfigBox()

        for _include in config:
            with open(_include, "r") as f:
                conf.update(yaml.load(f.read(), Loader=yaml.FullLoader))
            if verbose:
                console.print(f"Included {_include}")

        # self.metadata["conf"].update(conf)

        return self.metadata
