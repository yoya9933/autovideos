import unittest
import tempfile
from pathlib import Path

import auto_publish_youtube as ap
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

    def _write_bgm(self, song_dir: str, folder: str, filename: str = "track.mp3") -> str:
        bgm_dir = Path(song_dir) / folder
        bgm_dir.mkdir(parents=True, exist_ok=True)
        bgm_path = bgm_dir / filename
        bgm_path.write_bytes(b"fake-mp3")
        return f"{folder}/{filename}"

    def test_select_topic_bgm_file_uses_semiconductor_stock_folder(self):
        with tempfile.TemporaryDirectory() as song_dir:
            expected = self._write_bgm(song_dir, "semiconductor_stock")

            selected = ap._select_topic_bgm_file(
                title="投信買超台積電，NVIDIA GPU 供應鏈再升溫",
                summary="半導體與股市資金同步發酵",
                material_terms=["gpu processor", "computer chip"],
                song_dir=song_dir,
            )

        self.assertEqual(selected, expected)

    def test_select_topic_bgm_file_uses_security_fraud_folder(self):
        with tempfile.TemporaryDirectory() as song_dir:
            expected = self._write_bgm(song_dir, "security_fraud")

            selected = ap._select_topic_bgm_file(
                title="駭客攻擊造成個資外洩，詐騙風險升高",
                summary="資安事件牽動金融帳戶安全",
                material_terms=["cyber security"],
                song_dir=song_dir,
            )

        self.assertEqual(selected, expected)

    def test_select_topic_bgm_file_uses_ai_tools_folder(self):
        with tempfile.TemporaryDirectory() as song_dir:
            expected = self._write_bgm(song_dir, "ai_tools")

            selected = ap._select_topic_bgm_file(
                title="新的生成式 AI 工具讓簡報自動完成",
                summary="AI 產品更新帶來工作流程改變",
                material_terms=["artificial intelligence"],
                song_dir=song_dir,
            )

        self.assertEqual(selected, expected)

    def test_select_topic_bgm_file_falls_back_when_topic_folder_empty(self):
        with tempfile.TemporaryDirectory() as song_dir:
            selected = ap._select_topic_bgm_file(
                title="投信買超台積電，NVIDIA GPU 供應鏈再升溫",
                summary="半導體與股市資金同步發酵",
                material_terms=["gpu processor", "computer chip"],
                song_dir=song_dir,
            )

        self.assertEqual(selected, "")


if __name__ == "__main__":
    unittest.main()
