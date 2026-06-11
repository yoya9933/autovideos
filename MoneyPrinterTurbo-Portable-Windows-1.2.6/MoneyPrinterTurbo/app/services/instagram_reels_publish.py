from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from loguru import logger

from app.config import config
from app.services.platform_publish import PublishRequest, PublishResult


DEFAULT_GRAPH_API_BASE = "https://graph.facebook.com"


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _normalize_hashtag(tag: str) -> str:
    tag = tag.strip().replace(" ", "")
    if not tag:
        return ""
    return tag if tag.startswith("#") else f"#{tag}"


class InstagramReelsPublisher:
    platform_name = "instagram_reels"

    def __init__(self) -> None:
        self.enabled = _as_bool(
            os.getenv("INSTAGRAM_REELS_ENABLED", config.app.get("instagram_reels_enabled", False))
        )
        self.ig_user_id = os.getenv(
            "INSTAGRAM_IG_USER_ID",
            os.getenv("INSTAGRAM_USER_ID", config.app.get("instagram_ig_user_id", "")),
        ).strip()
        self.access_token = os.getenv(
            "INSTAGRAM_ACCESS_TOKEN",
            os.getenv("INSTAGRAM_PAGE_ACCESS_TOKEN", config.app.get("instagram_access_token", "")),
        ).strip()
        self.graph_api_base = os.getenv(
            "INSTAGRAM_GRAPH_API_BASE",
            config.app.get("instagram_graph_api_base", DEFAULT_GRAPH_API_BASE),
        ).strip().rstrip("/")
        self.api_version = os.getenv(
            "INSTAGRAM_GRAPH_API_VERSION",
            config.app.get("instagram_graph_api_version", "v23.0"),
        ).strip()
        self.video_url = os.getenv(
            "INSTAGRAM_REELS_VIDEO_URL",
            config.app.get("instagram_reels_video_url", ""),
        ).strip()
        self.video_url_template = os.getenv(
            "INSTAGRAM_REELS_VIDEO_URL_TEMPLATE",
            config.app.get("instagram_reels_video_url_template", ""),
        ).strip()
        self.caption_template = os.getenv(
            "INSTAGRAM_REELS_CAPTION_TEMPLATE",
            config.app.get(
                "instagram_reels_caption_template",
                "{title}\n\n{description}\n\n{hashtags}",
            ),
        )
        env_hashtags = os.getenv("INSTAGRAM_REELS_HASHTAGS", "")
        self.hashtags = [
            normalized
            for normalized in (_normalize_hashtag(tag) for tag in _as_list(env_hashtags or config.app.get("instagram_reels_hashtags", [])))
            if normalized
        ]
        self.share_to_feed = _as_bool(
            os.getenv(
                "INSTAGRAM_REELS_SHARE_TO_FEED",
                config.app.get("instagram_reels_share_to_feed", False),
            )
        )
        self.timeout = int(
            os.getenv("INSTAGRAM_REELS_TIMEOUT_SECONDS", config.app.get("instagram_reels_timeout_seconds", 60))
        )
        self.poll_interval = int(
            os.getenv(
                "INSTAGRAM_REELS_POLL_INTERVAL_SECONDS",
                config.app.get("instagram_reels_poll_interval_seconds", 60),
            )
        )
        self.poll_attempts = int(
            os.getenv(
                "INSTAGRAM_REELS_POLL_ATTEMPTS",
                config.app.get("instagram_reels_poll_attempts", 5),
            )
        )

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.ig_user_id
            and self.access_token
            and (self.video_url or self.video_url_template)
        )

    def _configuration_error(self) -> str:
        missing: list[str] = []
        if not self.enabled:
            missing.append("INSTAGRAM_REELS_ENABLED=true")
        if not self.ig_user_id:
            missing.append("INSTAGRAM_IG_USER_ID")
        if not self.access_token:
            missing.append("INSTAGRAM_ACCESS_TOKEN")
        if not (self.video_url or self.video_url_template):
            missing.append("INSTAGRAM_REELS_VIDEO_URL_TEMPLATE or INSTAGRAM_REELS_VIDEO_URL")
        return "missing Instagram Reels configuration: " + ", ".join(missing)

    def configuration_error(self) -> str:
        return self._configuration_error()

    def _build_caption(self, request: PublishRequest) -> str:
        request_hashtags = [
            normalized
            for normalized in (_normalize_hashtag(tag) for tag in request.hashtags)
            if normalized
        ]
        hashtags = " ".join(request_hashtags or self.hashtags)
        caption = self.caption_template.format(
            title=request.title,
            description=request.description,
            source=request.source_name,
            url=request.source_url,
            summary=request.summary,
            hashtags=hashtags,
        ).strip()
        return caption[:2200]

    def _build_video_url(self, request: PublishRequest) -> str:
        metadata_url = str(request.metadata.get("instagram_video_url", "") or "").strip()
        if metadata_url:
            return metadata_url
        if self.video_url:
            return self.video_url
        video_path = Path(request.video_path)
        return self.video_url_template.format(
            task_id=request.task_id,
            entry_id=request.entry_id,
            filename=video_path.name,
            stem=video_path.stem,
        )

    def _endpoint(self, suffix: str) -> str:
        return f"{self.graph_api_base}/{self.api_version}/{suffix.lstrip('/')}"

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        response = requests.request(method, url, timeout=self.timeout, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = {"text": response.text}
        if not response.ok:
            error = payload.get("error", payload)
            raise RuntimeError(f"Instagram API error {response.status_code}: {error}")
        return payload

    def create_reel_container(self, video_url: str, caption: str) -> dict:
        return self._request_json(
            "POST",
            self._endpoint(f"{self.ig_user_id}/media"),
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": str(self.share_to_feed).lower(),
                "access_token": self.access_token,
            },
        )

    def get_container_status(self, container_id: str) -> dict:
        return self._request_json(
            "GET",
            self._endpoint(container_id),
            params={
                "fields": "status_code,status",
                "access_token": self.access_token,
            },
        )

    def wait_for_container(self, container_id: str) -> dict:
        last_status: dict = {}
        attempts = max(self.poll_attempts, 1)
        for attempt in range(attempts):
            last_status = self.get_container_status(container_id)
            status_code = str(last_status.get("status_code", "")).upper()
            if status_code == "FINISHED":
                return last_status
            if status_code in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Instagram container status is {status_code}: {last_status}")
            if attempt < attempts - 1:
                time.sleep(max(self.poll_interval, 1))
        raise RuntimeError(f"Instagram container did not finish processing: {last_status}")

    def publish_container(self, container_id: str) -> dict:
        return self._request_json(
            "POST",
            self._endpoint(f"{self.ig_user_id}/media_publish"),
            data={
                "creation_id": container_id,
                "access_token": self.access_token,
            },
        )

    def publish(self, request: PublishRequest) -> PublishResult:
        if not self.is_configured():
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="not_configured",
                error=self._configuration_error(),
            )

        if not os.path.isfile(request.video_path):
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error=f"video file not found: {request.video_path}",
            )

        try:
            video_url = self._build_video_url(request)
            if not video_url.lower().startswith(("http://", "https://")):
                raise RuntimeError("Instagram Reels requires a public HTTP(S) video URL")

            caption = self._build_caption(request)
            container = self.create_reel_container(video_url=video_url, caption=caption)
            container_id = str(container.get("id", "")).strip()
            if not container_id:
                raise RuntimeError(f"Instagram media container response missing id: {container}")

            status = self.wait_for_container(container_id)
            publish_response = self.publish_container(container_id)
            media_id = str(publish_response.get("id", "")).strip()
            if not media_id:
                raise RuntimeError(f"Instagram publish response missing id: {publish_response}")

            logger.info(f"published Instagram Reel successfully: {media_id}")
            return PublishResult(
                platform=self.platform_name,
                success=True,
                status="published",
                remote_id=media_id,
                container_id=container_id,
                publish_id=media_id,
                raw_response={
                    "container": container,
                    "container_status": status,
                    "publish": publish_response,
                    "video_url": video_url,
                },
            )
        except Exception as exc:
            logger.error(f"Instagram Reels publish failed: {exc}")
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error=str(exc),
            )


instagram_reels_publisher = InstagramReelsPublisher()
