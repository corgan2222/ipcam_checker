from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, CameraResult


class AbstractPlugin(ABC):
    name: str

    @abstractmethod
    async def run(
        self,
        camera: CameraConfig,
        result: CameraResult,
        executor: ThreadPoolExecutor,
        settings: Settings,
    ) -> dict[str, Any]: ...
