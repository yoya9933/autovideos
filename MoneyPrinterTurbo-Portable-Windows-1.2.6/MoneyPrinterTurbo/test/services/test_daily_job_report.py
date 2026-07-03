import importlib
import io
import json
import tempfile
import types
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.services.daily_job_report import (
    DailyJobReport,
    build_daily_job_report,
    render_daily_job_report,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestDailyJobReport(unittest.TestCase):
    def test_build_daily_job_report_summarizes_jobs_by_local_date(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            jobs = root / "storage" / "auto_publish" / "jobs"
            status = root / "storage" / "auto_publish" / "publish_status"

            _write_json(
                jobs / "task-public.json",
                {
                    "task_id": "task-public",
                    "timestamp": "2026-06-12T16:10:00+00:00",
                    "title": "AI 晶片需求升溫",
                    "success": True,
                    "topic_profile": "consumer_money",
                    "privacy_status": "public",
                    "upload_video_id": "yt-public",
                    "material_terms": ["computer chip", "technology news"],
                },
            )
            _write_json(
                status / "task-public.json",
                {
                    "task_id": "task-public",
                    "source_name": "TechNews",
                    "source_url": "https://technews.tw/example",
                    "platforms": {
                        "youtube": {
                            "platform": "youtube",
                            "success": True,
                            "status": "published",
                            "remote_id": "yt-public",
                        }
                    },
                },
            )
            _write_json(
                jobs / "task-error.json",
                {
                    "task_id": "task-error",
                    "timestamp": "2026-06-13T04:05:00+00:00",
                    "title": "Error: 429 POST https://generativelanguage.googleapis.com",
                    "success": False,
                    "topic_profile": "tech",
                    "privacy_status": "public",
                    "failure_stage": "video_generation",
                    "error": "video generation failed",
                    "material_terms": ["technology news"],
                },
            )
            _write_json(
                jobs / "task-legacy.json",
                {
                    "task_id": "task-legacy",
                    "timestamp": "2026-06-13T05:05:00+00:00",
                    "title": "舊格式但已發布的影片",
                    "success": True,
                    "privacy_status": "private",
                    "upload_video_id": "yt-legacy",
                },
            )
            _write_json(
                jobs / "previous-day.json",
                {
                    "task_id": "previous-day",
                    "timestamp": "2026-06-12T10:00:00+00:00",
                    "title": "昨天的影片",
                    "success": True,
                    "privacy_status": "public",
                    "upload_video_id": "yt-old",
                },
            )

            report = build_daily_job_report(
                root_dir=str(root),
                report_date=date(2026, 6, 13),
                timezone_name="Asia/Taipei",
            )

        self.assertEqual(report.total_jobs, 3)
        self.assertEqual(report.success_count, 2)
        self.assertEqual(report.failure_count, 1)
        self.assertEqual(report.public_upload_count, 1)
        self.assertEqual(report.error_title_count, 1)
        self.assertEqual(report.source_counts["TechNews"], 1)
        self.assertEqual(report.material_term_counts["technology news"], 2)
        self.assertEqual(report.published_topic_profile_counts["consumer_money"], 1)
        self.assertEqual(report.published_topic_profile_counts["unknown"], 1)
        self.assertNotIn("tech", report.published_topic_profile_counts)

        body = render_daily_job_report(report)
        self.assertIn("VideoTurn Daily Report - 2026-06-13", body)
        self.assertIn("yt-public", body)
        self.assertIn("stage=video_generation", body)
        self.assertIn("Error-like titles: 1", body)
        self.assertIn("technology news: 2", body)
        self.assertIn("Published topic profiles", body)
        self.assertIn("consumer_money: 1", body)
        self.assertIn("unknown: 1", body)
        self.assertIn("Profile balance: tech=0, consumer_money=1 (not 3:3)", body)

    def test_render_daily_job_report_marks_three_by_three_balance(self):
        report = DailyJobReport(
            report_date=date(2026, 6, 13),
            timezone_name="Asia/Taipei",
            entries=(),
            source_counts=Counter(),
            material_term_counts=Counter(),
            published_topic_profile_counts=Counter(
                {"tech": 3, "consumer_money": 3}
            ),
        )

        body = render_daily_job_report(report)

        self.assertIn("Profile balance: tech=3, consumer_money=3 (3:3 OK)", body)

    def test_cli_send_email_uses_existing_email_notifier(self):
        cli = importlib.import_module("daily_job_report")
        report = DailyJobReport(
            report_date=date(2026, 6, 13),
            timezone_name="Asia/Taipei",
            entries=(),
            source_counts=Counter(),
            material_term_counts=Counter(),
        )
        sent_messages = []

        class FakeEmailNotifier:
            def send(self, subject: str, text: str) -> bool:
                sent_messages.append((subject, text))
                return True

        fake_notification = types.ModuleType("app.services.notification")
        fake_notification.EmailNotifier = FakeEmailNotifier

        with patch.object(cli, "build_daily_job_report", return_value=report):
            with patch.dict("sys.modules", {"app.services.notification": fake_notification}):
                with patch(
                    "sys.argv",
                    ["daily_job_report.py", "--date", "2026-06-13", "--send-email"],
                ):
                    with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        exit_code = cli.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0][0], "VideoTurn Daily Report - 2026-06-13")
        self.assertIn("Jobs: 0", sent_messages[0][1])
        self.assertIn("email report sent", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
