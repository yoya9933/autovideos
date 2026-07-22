import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

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

    def test_parse_args_accepts_topic_profile(self):
        args = ap._parse_args(["--dry-run", "--topic-profile", "consumer_money"])

        self.assertTrue(args.dry_run)
        self.assertEqual(args.topic_profile, "consumer_money")

    def test_parse_args_defaults_topic_profile_to_empty_override(self):
        args = ap._parse_args([])

        self.assertEqual(args.topic_profile, "")

    def test_daily_voice_rate_uses_voice_override_and_default(self):
        config.app["daily_voice_rate"] = 1.15
        config.app["daily_voice_rates"] = {
            "zh-TW-HsiaoYuNeural-Female": 1.40,
        }

        self.assertEqual(
            ap._get_daily_voice_rate("zh-TW-HsiaoYuNeural-Female"), 1.40
        )
        self.assertEqual(
            ap._get_daily_voice_rate("zh-TW-HsiaoChenNeural-Female"), 1.15
        )

    def test_job_context_persists_topic_profile_and_source_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(config, "root_dir", tmp_dir):
                job_path = ap._JobContext(
                    task_id="task-consumer",
                    entry_id="entry-consumer",
                    title="訂閱費突然上漲",
                    description="來源：Consumer News",
                    prompt="prompt",
                    topic_profile="consumer_money",
                    source_title="串流平台宣布調漲月費",
                    source_url="https://example.com/subscription",
                    source_feed="Consumer News",
                ).save(dry_run=True)

            payload = json.loads(Path(job_path).read_text(encoding="utf-8"))

        self.assertEqual(payload["topic_profile"], "consumer_money")
        self.assertEqual(payload["source_title"], "串流平台宣布調漲月費")
        self.assertEqual(payload["source_url"], "https://example.com/subscription")
        self.assertEqual(payload["source_feed"], "Consumer News")

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
