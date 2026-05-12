import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ipcam_checker.checks.rtsp import check_rtsp
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig


FFPROBE_OUTPUT_OK = json.dumps({
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "25/1",
            "bit_rate": "2097152",
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
        }
    ]
})

FFPROBE_OUTPUT_NO_VIDEO = json.dumps({"streams": [{"codec_type": "audio"}]})


@pytest.fixture
def camera():
    return CameraConfig(
        name="Test",
        ip="192.168.1.100",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
        rtsp_username="admin",
        rtsp_password="secret",
    )


@pytest.mark.asyncio
async def test_rtsp_ok(camera):
    settings = Settings()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = FFPROBE_OUTPUT_OK
    mock_proc.stderr = ""
    with patch("subprocess.run", return_value=mock_proc), \
         patch("ipcam_checker.checks.rtsp._get_ffprobe_path", return_value=Path("ffprobe")):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_rtsp(camera, "/stream1", settings, executor)
    assert result.ok is True
    assert result.width == 1920
    assert result.height == 1080
    assert result.fps == pytest.approx(25.0)
    assert result.codec == "h264"
    assert result.bitrate_kbps == pytest.approx(2048.0, rel=0.01)
    assert result.error is None


@pytest.mark.asyncio
async def test_rtsp_no_video_stream(camera):
    settings = Settings()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = FFPROBE_OUTPUT_NO_VIDEO
    mock_proc.stderr = ""
    with patch("subprocess.run", return_value=mock_proc), \
         patch("ipcam_checker.checks.rtsp._get_ffprobe_path", return_value=Path("ffprobe")):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_rtsp(camera, "/stream1", settings, executor)
    assert result.ok is False
    assert "no video stream" in result.error.lower()


@pytest.mark.asyncio
async def test_rtsp_connection_failed(camera):
    settings = Settings()
    with patch("subprocess.run", side_effect=OSError("connection refused")), \
         patch("ipcam_checker.checks.rtsp._get_ffprobe_path", return_value=Path("ffprobe")):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_rtsp(camera, "/stream1", settings, executor)
    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_rtsp_fractional_fps(camera):
    settings = Settings()
    output = json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264",
        "width": 1280, "height": 720, "r_frame_rate": "30000/1001", "bit_rate": "1000000"}]})
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = output
    mock_proc.stderr = ""
    with patch("subprocess.run", return_value=mock_proc), \
         patch("ipcam_checker.checks.rtsp._get_ffprobe_path", return_value=Path("ffprobe")):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_rtsp(camera, "/stream1", settings, executor)
    assert result.fps == pytest.approx(29.97, rel=0.01)
