from __future__ import annotations

from ipcam_checker.plugins.base import AbstractPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: list[AbstractPlugin] = []

    def register(self, plugin: AbstractPlugin) -> None:
        self._plugins.append(plugin)

    def all(self) -> list[AbstractPlugin]:
        return list(self._plugins)
