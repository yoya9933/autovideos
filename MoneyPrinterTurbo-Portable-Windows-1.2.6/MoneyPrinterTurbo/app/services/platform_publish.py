from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class PublishRequest:
    task_id: str
    entry_id: str
    video_path: str
    title: str
    description: str
    source_url: str = ""
    source_name: str = ""
    summary: str = ""
    hashtags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishResult:
    platform: str
    success: bool
    status: str
    remote_id: str = ""
    container_id: str = ""
    publish_id: str = ""
    error: str = ""
    dry_run: bool = False
    no_upload: bool = False
    raw_response: dict[str, Any] | None = None


class PlatformPublisher(Protocol):
    platform_name: str

    def is_configured(self) -> bool:
        ...

    def publish(self, request: PublishRequest) -> PublishResult:
        ...


PLATFORM_ALIASES = {
    "yt": "youtube",
    "youtube_shorts": "youtube",
    "instagram": "instagram_reels",
    "ig": "instagram_reels",
    "ig_reels": "instagram_reels",
    "reels": "instagram_reels",
    "facebook": "facebook_reels",
    "fb": "facebook_reels",
    "fb_reels": "facebook_reels",
    "page_reels": "facebook_reels",
}


def normalize_platform_name(platform: str) -> str:
    normalized = platform.strip().lower().replace("-", "_")
    return PLATFORM_ALIASES.get(normalized, normalized)


def parse_publish_platforms(value, default: tuple[str, ...] = ("youtube",)) -> list[str]:
    if not value:
        raw_platforms = list(default)
    elif isinstance(value, str):
        raw_platforms = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_platforms = [str(item).strip() for item in value]
    else:
        raw_platforms = [str(value).strip()]

    platforms: list[str] = []
    seen: set[str] = set()
    for platform in raw_platforms:
        if not platform:
            continue
        normalized = normalize_platform_name(platform)
        if normalized in seen:
            continue
        seen.add(normalized)
        platforms.append(normalized)

    return platforms or list(default)


def publish_result_to_dict(result: PublishResult) -> dict[str, Any]:
    return asdict(result)


def publish_results_to_dicts(results: list[PublishResult]) -> list[dict[str, Any]]:
    return [publish_result_to_dict(result) for result in results]


def _publish_state_path(root_dir: str, task_id: str) -> Path:
    state_dir = Path(root_dir) / "storage" / "auto_publish" / "publish_status"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{task_id}.json"


def save_publish_state(
    root_dir: str,
    request: PublishRequest,
    results: list[PublishResult],
) -> str:
    state_path = _publish_state_path(root_dir=root_dir, task_id=request.task_id)
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            state = {}
    else:
        state = {}

    platforms = state.get("platforms")
    if not isinstance(platforms, dict):
        platforms = {}

    for result in results:
        platforms[result.platform] = publish_result_to_dict(result)

    state.update(
        {
            "task_id": request.task_id,
            "entry_id": request.entry_id,
            "video_path": request.video_path,
            "title": request.title,
            "source_url": request.source_url,
            "source_name": request.source_name,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "platforms": platforms,
        }
    )

    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, default=str)

    return str(state_path)
