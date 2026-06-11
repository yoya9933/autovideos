from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests
from loguru import logger

from app.config import config


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# HTTP status codes that are transient and safe to retry
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_CHUNK_RETRIES: int = 3
_BACKOFF_BASE: int = 2  # sleep = BACKOFF_BASE ** attempt  (2 s → 4 s → 8 s)


@dataclass(frozen=True)
class YouTubeUploadResult:
    success: bool
    video_id: str = ""
    raw_response: dict | None = None
    error: str = ""


class YouTubeUploader:
    def __init__(self) -> None:
        self.enabled = config.app.get("youtube_upload_enabled", False)
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID", config.app.get("youtube_client_id", "")).strip()
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", config.app.get("youtube_client_secret", "")).strip()
        self.refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", config.app.get("youtube_refresh_token", "")).strip()
        self.privacy_status = os.getenv(
            "YOUTUBE_UPLOAD_PRIVACY_STATUS",
            config.app.get("youtube_upload_privacy_status", "unlisted"),
        )
        self.category_id = str(config.app.get("youtube_upload_category_id", "22")).strip()
        self.tags = config.app.get("youtube_upload_tags", ["shorts"])
        self.chunk_size = int(config.app.get("youtube_upload_chunk_size", 8 * 1024 * 1024))

    def is_configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret and self.refresh_token)

    def _refresh_access_token(self) -> str:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token", "")
        if not token:
            raise RuntimeError("missing access_token from Google token response")
        return token

    def _create_resumable_session(
        self,
        access_token: str,
        video_path: str,
        title: str,
        description: str,
    ) -> str:
        file_size = os.path.getsize(video_path)
        payload = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": self.tags,
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }
        response = requests.post(
            f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
            data=json.dumps(payload),
            timeout=30,
        )
        response.raise_for_status()
        location = response.headers.get("Location", "").strip()
        if not location:
            raise RuntimeError("missing resumable upload session url")
        return location

    def _upload_chunks(self, resumable_url: str, video_path: str) -> dict:
        file_size = os.path.getsize(video_path)
        with open(video_path, "rb") as file_handle:
            start = 0
            while start < file_size:
                chunk = file_handle.read(self.chunk_size)
                if not chunk:
                    break

                end = start + len(chunk) - 1
                chunk_accepted = False
                for attempt in range(_MAX_CHUNK_RETRIES + 1):
                    try:
                        response = requests.put(
                            resumable_url,
                            headers={
                                "Content-Length": str(len(chunk)),
                                "Content-Type": "video/mp4",
                                "Content-Range": f"bytes {start}-{end}/{file_size}",
                            },
                            data=chunk,
                            timeout=600,
                        )
                    except (
                        requests.exceptions.ConnectionError,
                        requests.exceptions.ReadTimeout,
                    ) as exc:
                        if attempt < _MAX_CHUNK_RETRIES:
                            wait = _BACKOFF_BASE ** (attempt + 1)
                            logger.warning(
                                f"chunk [{start}-{end}] network error "
                                f"(attempt {attempt + 1}/{_MAX_CHUNK_RETRIES}), "
                                f"retrying in {wait}s: {exc}"
                            )
                            time.sleep(wait)
                            continue
                        raise

                    if response.status_code in (200, 201):
                        return response.json()

                    if response.status_code == 308:  # chunk accepted, advance
                        chunk_accepted = True
                        break

                    if response.status_code in _RETRYABLE_STATUS:
                        if attempt < _MAX_CHUNK_RETRIES:
                            wait = _BACKOFF_BASE ** (attempt + 1)
                            logger.warning(
                                f"chunk [{start}-{end}] HTTP {response.status_code} "
                                f"(attempt {attempt + 1}/{_MAX_CHUNK_RETRIES}), "
                                f"retrying in {wait}s"
                            )
                            time.sleep(wait)
                            continue
                        response.raise_for_status()
                    else:
                        response.raise_for_status()

                if not chunk_accepted:
                    raise RuntimeError(
                        f"chunk [{start}-{end}] was not acknowledged after "
                        f"{_MAX_CHUNK_RETRIES} retries"
                    )
                start = end + 1

        raise RuntimeError("resumable upload ended without a final success response")

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        privacy_status: str | None = None,
    ) -> YouTubeUploadResult:
        if not self.is_configured():
            return YouTubeUploadResult(success=False, error="YouTube upload is not configured")

        if not os.path.isfile(video_path):
            return YouTubeUploadResult(success=False, error=f"video file not found: {video_path}")

        if privacy_status:
            self.privacy_status = privacy_status

        try:
            access_token = self._refresh_access_token()
            resumable_url = self._create_resumable_session(
                access_token=access_token,
                video_path=video_path,
                title=title,
                description=description,
            )
            response = self._upload_chunks(resumable_url=resumable_url, video_path=video_path)
            video_id = response.get("id", "")
            logger.info(f"uploaded to YouTube successfully: {video_id}")
            return YouTubeUploadResult(success=True, video_id=video_id, raw_response=response)
        except Exception as exc:
            logger.error(f"YouTube upload failed: {exc}")
            return YouTubeUploadResult(success=False, error=str(exc))

    def upload_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """
        Upload a custom thumbnail image for *video_id*.

        Requires the channel to have thumbnail upload permission (granted once
        the channel is verified).  Returns False silently on any error so the
        caller can continue without failing the whole job.
        """
        if not self.is_configured():
            return False
        if not os.path.isfile(thumbnail_path):
            logger.warning(f"thumbnail file not found, skipping upload: {thumbnail_path}")
            return False

        try:
            access_token = self._refresh_access_token()
            file_size = os.path.getsize(thumbnail_path)
            ext = os.path.splitext(thumbnail_path)[-1].lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"

            with open(thumbnail_path, "rb") as fh:
                response = requests.post(
                    "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
                    f"?videoId={video_id}&uploadType=media",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": mime,
                        "Content-Length": str(file_size),
                    },
                    data=fh.read(),
                    timeout=60,
                )

            if response.status_code in (200, 204):
                logger.success(f"thumbnail uploaded for video: {video_id}")
                return True

            logger.error(
                f"thumbnail upload failed: HTTP {response.status_code} – {response.text[:300]}"
            )
            return False

        except Exception as exc:
            logger.error(f"thumbnail upload error: {exc}")
            return False


youtube_uploader = YouTubeUploader()
