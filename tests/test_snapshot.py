import base64
import io
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import respx
from ipcam_checker.checks.check_snapshot import check_snapshot
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig
from PIL import Image


def _make_jpeg_bytes(width: int = 1920, height: int = 1080) -> bytes:
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def camera_with_snapshot():
    return CameraConfig(
        name="Test",
        ip="192.168.1.100",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
        snapshot_url="http://192.168.1.100/snapshot.jpg",
    )


@pytest.fixture
def camera_no_snapshot():
    return CameraConfig(
        name="Test",
        ip="192.168.1.100",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
    )


@pytest.mark.asyncio
@respx.mock
async def test_snapshot_ok(camera_with_snapshot):
    jpeg_bytes = _make_jpeg_bytes()
    respx.get("http://192.168.1.100/snapshot.jpg").mock(
        return_value=httpx.Response(200, content=jpeg_bytes)
    )
    settings = Settings(snapshot_width=600, snapshot_height=400)
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = await check_snapshot(camera_with_snapshot, settings, executor)
    assert result is not None
    decoded = base64.b64decode(result)
    img = Image.open(io.BytesIO(decoded))
    assert img.size == (600, 400)


@pytest.mark.asyncio
async def test_snapshot_no_url(camera_no_snapshot):
    settings = Settings()
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = await check_snapshot(camera_no_snapshot, settings, executor)
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_snapshot_http_error(camera_with_snapshot):
    respx.get("http://192.168.1.100/snapshot.jpg").mock(return_value=httpx.Response(401))
    settings = Settings()
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = await check_snapshot(camera_with_snapshot, settings, executor)
    assert result is None
