"""
Include external YAML files.

Note that inclusion happens relative to the document root, _not_ in-place within the plugins section.

The [blue]autoload[/] attribute is not effective for this plugin as it must be run at boot time.
"""

example = """
plugins:
  include:
  - file1.yaml
  - !path [ "~", projects/file2.yaml ]
"""

required_modules: dict[str, str] = {}
required_binaries: list[str] = []


import ruamel.yaml as yaml
from lib.util import ConfigBox, Style
from plugins import BasePlugin, MetadataType

# ==============================================================================


class Plugin(BasePlugin):
    key: str | None = None
    enabled: bool = False
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox, verbose: bool = False) -> MetadataType:
        "Include YAML files"

        conf: ConfigBox = ConfigBox()

        for _include in config:
            with open(_include, "r") as f:
                conf.update(yaml.load(f.read(), Loader=yaml.SafeLoader))
            if verbose:
                self.print(f"Included {_include}", Style.SUCCESS)

        # self.metadata["conf"].update(conf)

        return self.metadata
