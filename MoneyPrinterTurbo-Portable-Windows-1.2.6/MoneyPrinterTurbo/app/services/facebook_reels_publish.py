from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

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


def _collect_status_markers(value: Any) -> set[str]:
    markers: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            markers.update(_collect_status_markers(item))
    elif isinstance(value, list):
        for item in value:
            markers.update(_collect_status_markers(item))
    elif isinstance(value, str):
        markers.add(value.strip().lower())
    return markers


class FacebookReelsPublisher:
    platform_name = "facebook_reels"

    def __init__(self) -> None:
        self.enabled = _as_bool(
            os.getenv("FACEBOOK_REELS_ENABLED", config.app.get("facebook_reels_enabled", False))
        )
        self.page_id = os.getenv(
            "FACEBOOK_PAGE_ID",
            config.app.get("facebook_page_id", ""),
        ).strip()
        self.page_access_token = os.getenv(
            "FACEBOOK_PAGE_ACCESS_TOKEN",
            config.app.get("facebook_page_access_token", ""),
        ).strip()
        self.graph_api_base = os.getenv(
            "FACEBOOK_GRAPH_API_BASE",
            config.app.get("facebook_graph_api_base", DEFAULT_GRAPH_API_BASE),
        ).strip().rstrip("/")
        self.api_version = os.getenv(
            "FACEBOOK_API_VERSION",
            os.getenv(
                "FACEBOOK_GRAPH_API_VERSION",
                config.app.get(
                    "facebook_api_version",
                    config.app.get("facebook_graph_api_version", "v23.0"),
                ),
            ),
        ).strip()
        self.video_url = os.getenv(
            "FACEBOOK_REELS_VIDEO_URL",
            config.app.get("facebook_reels_video_url", ""),
        ).strip()
        self.video_url_template = os.getenv(
            "FACEBOOK_REELS_VIDEO_URL_TEMPLATE",
            config.app.get("facebook_reels_video_url_template", ""),
        ).strip()
        self.caption_template = os.getenv(
            "FACEBOOK_REELS_CAPTION_TEMPLATE",
            config.app.get(
                "facebook_reels_caption_template",
                "{title}\n\n{description}\n\n{hashtags}",
            ),
        )
        env_hashtags = os.getenv("FACEBOOK_REELS_HASHTAGS", "")
        self.hashtags = [
            normalized
            for normalized in (
                _normalize_hashtag(tag)
                for tag in _as_list(env_hashtags or config.app.get("facebook_reels_hashtags", []))
            )
            if normalized
        ]
        self.timeout = int(
            os.getenv("FACEBOOK_REELS_TIMEOUT_SECONDS", config.app.get("facebook_reels_timeout_seconds", 60))
        )
        self.poll_interval = int(
            os.getenv(
                "FACEBOOK_REELS_POLL_INTERVAL_SECONDS",
                config.app.get("facebook_reels_poll_interval_seconds", 30),
            )
        )
        self.poll_attempts = int(
            os.getenv(
                "FACEBOOK_REELS_POLL_ATTEMPTS",
                config.app.get("facebook_reels_poll_attempts", 10),
            )
        )

    def is_configured(self) -> bool:
        return bool(self.enabled and self.page_id and self.page_access_token)

    def _configuration_error(self) -> str:
        missing: list[str] = []
        if not self.enabled:
            missing.append("FACEBOOK_REELS_ENABLED=true")
        if not self.page_id:
            missing.append("FACEBOOK_PAGE_ID")
        if not self.page_access_token:
            missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
        return "missing Facebook Reels configuration: " + ", ".join(missing)

    def configuration_error(self) -> str:
        return self._configuration_error()

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
            raise RuntimeError(f"Facebook API error {response.status_code}: {error}")
        return payload

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
        return caption[:63206]

    def _build_video_url(self, request: PublishRequest) -> str:
        metadata_url = str(request.metadata.get("facebook_video_url", "") or "").strip()
        if metadata_url:
            return metadata_url
        if self.video_url:
            return self.video_url
        if not self.video_url_template:
            return ""
        video_path = Path(request.video_path)
        return self.video_url_template.format(
            task_id=request.task_id,
            entry_id=request.entry_id,
            filename=video_path.name,
            stem=video_path.stem,
        )

    def start_upload_session(self, file_url: str = "") -> dict:
        data = {
            "upload_phase": "start",
            "access_token": self.page_access_token,
        }
        if file_url:
            data["file_url"] = file_url
        return self._request_json(
            "POST",
            self._endpoint(f"{self.page_id}/video_reels"),
            data=data,
        )

    def upload_local_file(self, upload_url: str, video_path: str) -> dict:
        file_size = os.path.getsize(video_path)
        with open(video_path, "rb") as file_handle:
            response = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {self.page_access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                data=file_handle,
                timeout=max(self.timeout, 60),
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {"text": response.text}
        if not response.ok:
            error = payload.get("error", payload)
            raise RuntimeError(f"Facebook Reels file upload error {response.status_code}: {error}")
        return payload

    def get_video_status(self, video_id: str) -> dict:
        return self._request_json(
            "GET",
            self._endpoint(video_id),
            params={
                "fields": "status",
                "access_token": self.page_access_token,
            },
        )

    def wait_for_video_ready(self, video_id: str) -> dict:
        last_status: dict = {}
        attempts = max(self.poll_attempts, 1)
        failure_markers = {"error", "failed", "expired"}
        ready_markers = {"complete", "completed", "finished", "ready"}
        for attempt in range(attempts):
            last_status = self.get_video_status(video_id)
            markers = _collect_status_markers(last_status)
            if markers & failure_markers:
                raise RuntimeError(f"Facebook Reel video status failed: {last_status}")
            if markers & ready_markers:
                return last_status
            if attempt < attempts - 1:
                time.sleep(max(self.poll_interval, 1))
        raise RuntimeError(f"Facebook Reel video did not finish processing: {last_status}")

    def publish_reel(self, video_id: str, caption: str) -> dict:
        return self._request_json(
            "POST",
            self._endpoint(f"{self.page_id}/video_reels"),
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
                "access_token": self.page_access_token,
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

        file_url = self._build_video_url(request)
        if file_url and not file_url.lower().startswith(("http://", "https://")):
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error="Facebook Reels CDN upload requires a public HTTP(S) video URL",
            )

        if not file_url and not os.path.isfile(request.video_path):
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error=f"video file not found: {request.video_path}",
            )

        try:
            caption = self._build_caption(request)
            start_response = self.start_upload_session(file_url=file_url)
            video_id = str(start_response.get("video_id", "") or start_response.get("id", "")).strip()
            if not video_id:
                raise RuntimeError(f"Facebook Reels start response missing video_id: {start_response}")

            upload_response: dict = {}
            if not file_url:
                upload_url = str(start_response.get("upload_url", "")).strip()
                if not upload_url:
                    raise RuntimeError(f"Facebook Reels start response missing upload_url: {start_response}")
                upload_response = self.upload_local_file(upload_url=upload_url, video_path=request.video_path)

            status = self.wait_for_video_ready(video_id)
            publish_response = self.publish_reel(video_id=video_id, caption=caption)
            publish_id = str(
                publish_response.get("post_id", "")
                or publish_response.get("id", "")
                or video_id
            ).strip()

            logger.info(f"published Facebook Reel successfully: {publish_id}")
            return PublishResult(
                platform=self.platform_name,
                success=True,
                status="published",
                remote_id=video_id,
                container_id=video_id,
                publish_id=publish_id,
                raw_response={
                    "start": start_response,
                    "upload": upload_response,
                    "status": status,
                    "publish": publish_response,
                    "file_url": file_url,
                    "upload_source": "cdn" if file_url else "local_file",
                },
            )
        except Exception as exc:
            logger.error(f"Facebook Reels publish failed: {exc}")
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error=str(exc),
            )


facebook_reels_publisher = FacebookReelsPublisher()
