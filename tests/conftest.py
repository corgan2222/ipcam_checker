import pytest


@pytest.fixture
def settings():
    from ipcam_checker.config import Settings
    return Settings()


@pytest.fixture
def camera():
    from ipcam_checker.models import CameraConfig
    return CameraConfig(
        name="Test Cam",
        ip="192.168.1.100",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
        rtsp_username="admin",
        rtsp_password="secret",
        snapshot_url="http://192.168.1.100/snapshot.jpg",
    )
