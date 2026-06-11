import os
import unittest
from unittest.mock import patch

from app.config import config
from app.services.notification import EmailNotifier, NotificationContext, TelegramNotifier


class TestTelegramNotifier(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_send_skips_when_not_configured(self):
        config.app["telegram_notify_enabled"] = True
        config.app["telegram_bot_token"] = ""
        config.app["telegram_chat_id"] = ""

        notifier = TelegramNotifier()

        with patch("app.services.notification.requests.post") as post:
            self.assertFalse(notifier.notify_failure(NotificationContext(task_id="task-1", stage="test")))

        post.assert_not_called()

    def test_success_notification_posts_plain_text(self):
        config.app["telegram_notify_enabled"] = True
        config.app["telegram_bot_token"] = "bot-token"
        config.app["telegram_chat_id"] = "chat-id"

        notifier = TelegramNotifier()

        with patch("app.services.notification.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            sent = notifier.notify_success(
                NotificationContext(
                    task_id="task-1",
                    title="測試影片",
                    youtube_video_id="abc123",
                    privacy_status="public",
                    video_source="pexels",
                    job_path="storage/auto_publish/jobs/task-1.json",
                )
            )

        self.assertTrue(sent)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertIn("VideoTurn publish succeeded", payload["text"])
        self.assertIn("youtube_id: abc123", payload["text"])
        self.assertNotIn("parse_mode", payload)


class TestEmailNotifier(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_send_skips_when_not_configured(self):
        config.app["email_notify_enabled"] = True
        config.app["email_smtp_username"] = ""
        config.app["email_smtp_password"] = ""
        config.app["email_notify_to"] = []

        with patch.dict(os.environ, {}, clear=True):
            notifier = EmailNotifier()

            with patch("app.services.notification.smtplib.SMTP") as smtp:
                self.assertFalse(notifier.notify_failure(NotificationContext(task_id="task-1", stage="test")))

        smtp.assert_not_called()

    def test_success_notification_sends_gmail_smtp_message(self):
        config.app["email_notify_enabled"] = True
        config.app["email_smtp_host"] = "smtp.gmail.com"
        config.app["email_smtp_port"] = 587
        config.app["email_smtp_use_tls"] = True
        config.app["email_smtp_username"] = "sender@gmail.com"
        config.app["email_smtp_password"] = "app-password"
        config.app["email_notify_from"] = "sender@gmail.com"
        config.app["email_notify_to"] = ["owner@example.com"]

        with patch.dict(os.environ, {}, clear=True):
            notifier = EmailNotifier()

            with patch("app.services.notification.smtplib.SMTP") as smtp_class:
                smtp = smtp_class.return_value.__enter__.return_value
                sent = notifier.notify_success(
                    NotificationContext(
                        task_id="task-1",
                        title="測試影片",
                        youtube_video_id="abc123",
                        privacy_status="public",
                        video_source="pexels",
                        job_path="storage/auto_publish/jobs/task-1.json",
                    )
                )

        self.assertTrue(sent)
        smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("sender@gmail.com", "app-password")
        smtp.send_message.assert_called_once()

        message = smtp.send_message.call_args.args[0]
        self.assertIn("VideoTurn success", message["Subject"])
        self.assertEqual(message["From"], "sender@gmail.com")
        self.assertEqual(message["To"], "owner@example.com")
        self.assertIn("youtube_id: abc123", message.get_content())


if __name__ == "__main__":
    unittest.main()
