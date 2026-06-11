import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import config
from app.models.schema import VideoParams
from auto_publish_youtube import _resolve_video_source, _run_quality_gate


class TestAutoPublishQualityGate(unittest.TestCase):
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

    def test_resolve_video_source_blocks_missing_pexels_key_by_default(self):
        config.app["daily_video_source"] = "pexels"
        config.app["pexels_api_keys"] = []
        config.app["pixabay_api_keys"] = []
        config.app["daily_allow_local_material_fallback"] = False

        with self.assertRaisesRegex(ValueError, "pexels_api_keys is empty"):
            _resolve_video_source()

    def test_resolve_video_source_allows_local_fallback_when_enabled(self):
        config.app["daily_video_source"] = "pexels"
        config.app["pexels_api_keys"] = []
        config.app["pixabay_api_keys"] = []
        config.app["daily_allow_local_material_fallback"] = True

        self.assertEqual(_resolve_video_source(), "local")

    def test_quality_gate_passes_basic_generated_video(self):
        config.app["daily_quality_gate_enabled"] = True
        config.app["daily_quality_gate_min_video_bytes"] = 1
        config.app["daily_quality_gate_min_duration_seconds"] = 20
        config.app["daily_quality_gate_max_duration_seconds"] = 180
        config.app["daily_quality_gate_min_script_cjk_chars"] = 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "final.mp4"
            subtitle_path = Path(tmp_dir) / "subtitle.srt"
            video_path.write_bytes(b"video")
            subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n測試\n", encoding="utf-8")

            with patch("auto_publish_youtube._get_video_duration", return_value=60.0):
                issues = _run_quality_gate(
                    result={
                        "script": "測試。",
                        "audio_duration": 60,
                        "subtitle_path": str(subtitle_path),
                        "materials": ["clip-1.mp4"],
                    },
                    video_path=str(video_path),
                    title="測試影片",
                    description="來源：TechNews",
                    params=self._params(),
                )

        self.assertEqual(issues, [])

    def test_quality_gate_blocks_missing_subtitle_and_bad_duration(self):
        config.app["daily_quality_gate_enabled"] = True
        config.app["daily_quality_gate_min_video_bytes"] = 1
        config.app["daily_quality_gate_min_duration_seconds"] = 20
        config.app["daily_quality_gate_min_script_cjk_chars"] = 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "final.mp4"
            video_path.write_bytes(b"video")

            with patch("auto_publish_youtube._get_video_duration", return_value=5.0):
                issues = _run_quality_gate(
                    result={
                        "script": "測試。",
                        "audio_duration": 60,
                        "materials": ["clip-1.mp4"],
                    },
                    video_path=str(video_path),
                    title="測試影片",
                    description="來源：TechNews",
                    params=self._params(),
                )

        self.assertIn("video duration is too short: 5.0s", issues)
        self.assertIn("subtitle file is missing", issues)


if __name__ == "__main__":
    unittest.main()
