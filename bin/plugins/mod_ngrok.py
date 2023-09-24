"""
[bold cyan]Configure Ngrok agent.[/]

  ngrok:
    tunnels:
      django:
        addr: 8000
        schemes:
        - https
        inspect: false
        proto: http

This plugin's config mirrors the ngrok config as documented here:

https://ngrok.com/docs/secure-tunnels/ngrok-agent/reference/config/#tunnel-definitions
"""

from typing import Callable

from lib.plugins import PluginTarget


# ==============================================================================


def start_ngrok_agent():
    return {}


# ==============================================================================


key: str | None = None  # "ngrok"
target: PluginTarget = PluginTarget.ENV
load: Callable = start_ngrok_agent
