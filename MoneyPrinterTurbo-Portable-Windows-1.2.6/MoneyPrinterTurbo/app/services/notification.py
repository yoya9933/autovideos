from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import requests
from loguru import logger

from app.config import config


TELEGRAM_API_BASE = "https://api.telegram.org"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


def _youtube_url(video_id: str) -> str:
    """Return the full watch URL for a video ID, or an empty string."""
    vid = (video_id or "").strip()
    return YOUTUBE_WATCH_URL.format(video_id=vid) if vid else ""


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


@dataclass(frozen=True)
class NotificationContext:
    task_id: str
    title: str = ""
    youtube_video_id: str = ""
    privacy_status: str = ""
    video_source: str = ""
    job_path: str = ""
    stage: str = ""
    error: str = ""
    warning: str = ""


class TelegramNotifier:
    def __init__(self) -> None:
        self.enabled = _as_bool(config.app.get("telegram_notify_enabled", False))
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", config.app.get("telegram_bot_token", "")).strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", config.app.get("telegram_chat_id", "")).strip()
        self.timeout = int(config.app.get("telegram_notify_timeout", 15))

    def is_configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.is_configured():
            logger.debug("telegram notification skipped; notifier is not configured")
            return False

        text = (text or "").strip()
        if not text:
            return False

        try:
            response = requests.post(
                f"{TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text[:3900],
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(f"telegram notification failed: {exc}")
            return False

    def notify_success(self, ctx: NotificationContext) -> bool:
        lines = [
            "VideoTurn publish succeeded",
            f"title: {ctx.title}",
            f"youtube_id: {ctx.youtube_video_id}",
        ]
        url = _youtube_url(ctx.youtube_video_id)
        if url:
            lines.append(f"url: {url}")
        lines += [
            f"privacy: {ctx.privacy_status}",
            f"video_source: {ctx.video_source}",
            f"task_id: {ctx.task_id}",
            f"job_json: {ctx.job_path}",
        ]
        return self.send("\n".join(lines))

    def notify_failure(self, ctx: NotificationContext) -> bool:
        lines = [
            "VideoTurn publish failed",
            f"stage: {ctx.stage or 'unknown'}",
            f"error: {ctx.error or 'unknown error'}",
            f"task_id: {ctx.task_id}",
        ]
        if ctx.job_path:
            lines.append(f"job_json: {ctx.job_path}")
        return self.send("\n".join(lines))

    def notify_warning(self, ctx: NotificationContext) -> bool:
        lines = [
            "VideoTurn publish warning",
            f"stage: {ctx.stage or 'warning'}",
            f"warning: {ctx.warning or 'unknown warning'}",
            f"task_id: {ctx.task_id}",
        ]
        if ctx.youtube_video_id:
            lines.append(f"youtube_id: {ctx.youtube_video_id}")
            url = _youtube_url(ctx.youtube_video_id)
            if url:
                lines.append(f"url: {url}")
        if ctx.job_path:
            lines.append(f"job_json: {ctx.job_path}")
        return self.send("\n".join(lines))


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


class EmailNotifier:
    def __init__(self) -> None:
        self.enabled = _as_bool(config.app.get("email_notify_enabled", False))
        self.smtp_host = os.getenv("EMAIL_NOTIFY_SMTP_HOST", config.app.get("email_smtp_host", "smtp.gmail.com")).strip()
        self.smtp_port = int(os.getenv("EMAIL_NOTIFY_SMTP_PORT", config.app.get("email_smtp_port", 587)))
        self.use_tls = _as_bool(os.getenv("EMAIL_NOTIFY_USE_TLS", config.app.get("email_smtp_use_tls", True)), True)
        self.username = os.getenv("EMAIL_NOTIFY_USERNAME", config.app.get("email_smtp_username", "")).strip()
        self.password = os.getenv("EMAIL_NOTIFY_PASSWORD", config.app.get("email_smtp_password", "")).strip()
        self.from_addr = os.getenv("EMAIL_NOTIFY_FROM", config.app.get("email_notify_from", "")).strip() or self.username
        env_to = os.getenv("EMAIL_NOTIFY_TO", "")
        self.to_addrs = _as_list(env_to or config.app.get("email_notify_to", []))
        self.timeout = int(config.app.get("email_notify_timeout", 20))

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.smtp_host
            and self.smtp_port
            and self.username
            and self.password
            and self.from_addr
            and self.to_addrs
        )

    def send(self, subject: str, text: str) -> bool:
        if not self.is_configured():
            logger.debug("email notification skipped; notifier is not configured")
            return False

        text = (text or "").strip()
        if not text:
            return False

        try:
            message = EmailMessage()
            message["Subject"] = subject[:180]
            message["From"] = self.from_addr
            message["To"] = ", ".join(self.to_addrs)
            message.set_content(text[:12000])

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(message)
            return True
        except Exception as exc:
            logger.warning(f"email notification failed: {exc}")
            return False

    def notify_success(self, ctx: NotificationContext) -> bool:
        subject = f"VideoTurn success: {ctx.title or ctx.youtube_video_id or ctx.task_id}"
        lines = [
            "VideoTurn publish succeeded",
            f"title: {ctx.title}",
            f"youtube_id: {ctx.youtube_video_id}",
        ]
        url = _youtube_url(ctx.youtube_video_id)
        if url:
            lines.append(f"url: {url}")
        lines += [
            f"privacy: {ctx.privacy_status}",
            f"video_source: {ctx.video_source}",
            f"task_id: {ctx.task_id}",
            f"job_json: {ctx.job_path}",
        ]
        return self.send(subject, "\n".join(lines))

    def notify_failure(self, ctx: NotificationContext) -> bool:
        subject = f"VideoTurn failed: {ctx.stage or ctx.task_id}"
        lines = [
            "VideoTurn publish failed",
            f"stage: {ctx.stage or 'unknown'}",
            f"error: {ctx.error or 'unknown error'}",
            f"task_id: {ctx.task_id}",
        ]
        if ctx.title:
            lines.append(f"title: {ctx.title}")
        if ctx.job_path:
            lines.append(f"job_json: {ctx.job_path}")
        return self.send(subject, "\n".join(lines))

    def notify_warning(self, ctx: NotificationContext) -> bool:
        subject = f"VideoTurn warning: {ctx.stage or ctx.task_id}"
        lines = [
            "VideoTurn publish warning",
            f"stage: {ctx.stage or 'warning'}",
            f"warning: {ctx.warning or 'unknown warning'}",
            f"task_id: {ctx.task_id}",
        ]
        if ctx.title:
            lines.append(f"title: {ctx.title}")
        if ctx.youtube_video_id:
            lines.append(f"youtube_id: {ctx.youtube_video_id}")
            url = _youtube_url(ctx.youtube_video_id)
            if url:
                lines.append(f"url: {url}")
        if ctx.job_path:
            lines.append(f"job_json: {ctx.job_path}")
        return self.send(subject, "\n".join(lines))


class NotificationService:
    def __init__(self) -> None:
        self.notifiers = [EmailNotifier(), TelegramNotifier()]

    def notify_success(self, ctx: NotificationContext) -> bool:
        sent = False
        for notifier in self.notifiers:
            sent = notifier.notify_success(ctx) or sent
        return sent

    def notify_failure(self, ctx: NotificationContext) -> bool:
        sent = False
        for notifier in self.notifiers:
            sent = notifier.notify_failure(ctx) or sent
        return sent

    def notify_warning(self, ctx: NotificationContext) -> bool:
        sent = False
        for notifier in self.notifiers:
            sent = notifier.notify_warning(ctx) or sent
        return sent


notification_service = NotificationService()
telegram_notifier = TelegramNotifier()
