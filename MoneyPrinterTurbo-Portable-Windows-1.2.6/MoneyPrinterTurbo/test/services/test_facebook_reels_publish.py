import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.facebook_reels_publish import FacebookReelsPublisher
from app.services.platform_publish import PublishRequest, parse_publish_platforms


FACEBOOK_ENV = {
    "FACEBOOK_REELS_ENABLED": "true",
    "FACEBOOK_PAGE_ID": "page-123",
    "FACEBOOK_PAGE_ACCESS_TOKEN": "token-123",
    "FACEBOOK_API_VERSION": "v99.0",
    "FACEBOOK_REELS_POLL_ATTEMPTS": "1",
}


def _request(video_path: str, metadata: dict | None = None) -> PublishRequest:
    return PublishRequest(
        task_id="task-1",
        entry_id="entry-1",
        video_path=video_path,
        title="Short title",
        description="Short description",
        source_url="https://example.com/article",
        source_name="Example Feed",
        summary="Summary",
        hashtags=["shorts", "news"],
        metadata=metadata or {},
    )


class TestFacebookReelsPublisher(unittest.TestCase):
    def test_platform_aliases_include_facebook_reels(self):
        platforms = parse_publish_platforms("yt,fb-reels,page-reels,facebook")

        self.assertEqual(platforms, ["youtube", "facebook_reels"])

    def test_local_file_upload_flow_publishes_reel(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "final.mp4"
            video_path.write_bytes(b"video")

            with patch.dict(os.environ, FACEBOOK_ENV, clear=False):
                publisher = FacebookReelsPublisher()
                publisher.start_upload_session = Mock(
                    return_value={"video_id": "video-123", "upload_url": "https://upload.example/video"}
                )
                publisher.upload_local_file = Mock(return_value={"success": True})
                publisher.wait_for_video_ready = Mock(
                    return_value={"status": {"processing_phase": {"status": "complete"}}}
                )
                publisher.publish_reel = Mock(return_value={"post_id": "post-123"})

                result = publisher.publish(_request(str(video_path)))

        self.assertTrue(result.success)
        self.assertEqual(result.platform, "facebook_reels")
        self.assertEqual(result.status, "published")
        self.assertEqual(result.remote_id, "video-123")
        self.assertEqual(result.publish_id, "post-123")
        publisher.start_upload_session.assert_called_once_with(file_url="")
        publisher.upload_local_file.assert_called_once_with(
            upload_url="https://upload.example/video",
            video_path=str(video_path),
        )
        publisher.wait_for_video_ready.assert_called_once_with("video-123")
        caption = publisher.publish_reel.call_args.kwargs["caption"]
        self.assertIn("Short title", caption)
        self.assertIn("#shorts #news", caption)

    def test_cdn_url_flow_skips_local_file_upload(self):
        env = dict(FACEBOOK_ENV)
        env["FACEBOOK_REELS_VIDEO_URL_TEMPLATE"] = "https://cdn.example.com/videos/{filename}"

        with patch.dict(os.environ, env, clear=False):
            publisher = FacebookReelsPublisher()
            publisher.start_upload_session = Mock(return_value={"video_id": "video-456"})
            publisher.upload_local_file = Mock()
            publisher.wait_for_video_ready = Mock(
                return_value={"status": {"processing_phase": {"status": "complete"}}}
            )
            publisher.publish_reel = Mock(return_value={"id": "video-456"})

            result = publisher.publish(_request("C:\\videos\\final.mp4"))

        self.assertTrue(result.success)
        self.assertEqual(result.remote_id, "video-456")
        publisher.start_upload_session.assert_called_once_with(
            file_url="https://cdn.example.com/videos/final.mp4"
        )
        publisher.upload_local_file.assert_not_called()
        self.assertEqual(result.raw_response["upload_source"], "cdn")


if __name__ == "__main__":
    unittest.main()
