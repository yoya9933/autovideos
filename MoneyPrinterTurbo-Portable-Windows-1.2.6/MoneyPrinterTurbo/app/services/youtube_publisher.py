from __future__ import annotations

from app.services.platform_publish import PublishRequest, PublishResult
from app.services.youtube_upload import youtube_uploader


class YouTubePublisher:
    platform_name = "youtube"

    def is_configured(self) -> bool:
        return youtube_uploader.is_configured()

    def configuration_error(self) -> str:
        return "youtube upload is not configured"

    def publish(self, request: PublishRequest) -> PublishResult:
        privacy_status = str(request.metadata.get("privacy_status", "") or "").strip() or None
        result = youtube_uploader.upload_video(
            video_path=request.video_path,
            title=request.title,
            description=request.description,
            privacy_status=privacy_status,
        )
        if not result.success:
            return PublishResult(
                platform=self.platform_name,
                success=False,
                status="failed",
                error=result.error,
                raw_response=result.raw_response,
            )

        return PublishResult(
            platform=self.platform_name,
            success=True,
            status="published",
            remote_id=result.video_id,
            publish_id=result.video_id,
            raw_response=result.raw_response,
        )


youtube_publisher = YouTubePublisher()
