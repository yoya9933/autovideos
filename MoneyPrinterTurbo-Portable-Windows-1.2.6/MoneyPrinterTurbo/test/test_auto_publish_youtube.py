import unittest

from app.config import config
from app.models.schema import VideoParams
from auto_publish_youtube import _resolve_video_source


class TestAutoPublish(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _params(self) -> VideoParams:
        return VideoParams(
            video_subject="測試影片",
            video_source="pexels",
            subtitle_enabled=True,
        )

    def test_resolve_video_source_falls_back_to_local_when_api_keys_missing(self):
        config.app["daily_video_source"] = "pexels"
        config.app["pexels_api_keys"] = []
        config.app["pixabay_api_keys"] = []
        config.app["daily_allow_local_material_fallback"] = False

        self.assertEqual(_resolve_video_source(), "local")

    def test_resolve_video_source_allows_local_fallback_when_enabled(self):
        config.app["daily_video_source"] = "pexels"
        config.app["pexels_api_keys"] = []
        config.app["pixabay_api_keys"] = []
        config.app["daily_allow_local_material_fallback"] = True

        self.assertEqual(_resolve_video_source(), "local")


if __name__ == "__main__":
    unittest.main()
