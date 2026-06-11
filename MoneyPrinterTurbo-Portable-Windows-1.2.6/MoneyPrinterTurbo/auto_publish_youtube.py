from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import state as _state_module, task, video as video_service
from app.services.facebook_reels_publish import facebook_reels_publisher
from app.services.notification import NotificationContext, notification_service
from app.services.instagram_reels_publish import instagram_reels_publisher
from app.services.platform_publish import (
    PlatformPublisher,
    PublishRequest,
    PublishResult,
    parse_publish_platforms,
    publish_results_to_dicts,
    save_publish_state,
)
from app.services.rss_ingest import (
    build_script_prompt,
    collect_candidate_entries,
    describe_source_context,
    fetch_article_text,
    generate_video_title,
    has_enough_source_context,
    load_seen_entries,
    save_seen_entries,
    select_best_entry_for_video,
)
from app.services.thumbnail import generate_thumbnail
from app.services.youtube_publisher import youtube_publisher
from app.services.youtube_upload import youtube_uploader


def _get_feed_urls() -> list[str]:
    feeds = config.app.get("daily_rss_feeds", [])
    if isinstance(feeds, str):
        feeds = [feeds]
    return [str(feed).strip() for feed in feeds if str(feed).strip()]


def _get_state_file() -> str:
    state_file = config.app.get("daily_rss_state_file", "storage/auto_publish/seen.json")
    if os.path.isabs(state_file):
        return state_file
    return str(Path(config.root_dir) / state_file)


def _get_config_value(key: str, default):
    value = config.app.get(key, default)
    return value if value not in (None, "") else default


def _get_config_bool(key: str, default: bool = False) -> bool:
    value = config.app.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _get_config_list(key: str) -> list[str]:
    value = config.app.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _get_publish_platforms(raw_value=None) -> list[str]:
    configured = raw_value if raw_value else config.app.get("daily_publish_platforms", ["youtube"])
    return parse_publish_platforms(configured, default=("youtube",))


def _get_publishers(platforms: list[str]) -> list[PlatformPublisher]:
    registry: dict[str, PlatformPublisher] = {
        youtube_publisher.platform_name: youtube_publisher,
        instagram_reels_publisher.platform_name: instagram_reels_publisher,
        facebook_reels_publisher.platform_name: facebook_reels_publisher,
    }
    unknown = [platform for platform in platforms if platform not in registry]
    if unknown:
        raise ValueError(f"unknown publish platform(s): {', '.join(unknown)}")
    return [registry[platform] for platform in platforms]


def _make_publish_request(
    task_id: str,
    entry_id: str,
    video_path: str,
    title: str,
    description: str,
    source_url: str,
    source_name: str,
    summary: str,
    hashtags: list[str],
    privacy_status: str,
) -> PublishRequest:
    return PublishRequest(
        task_id=task_id,
        entry_id=entry_id,
        video_path=video_path,
        title=title,
        description=description,
        source_url=source_url,
        source_name=source_name,
        summary=summary,
        hashtags=hashtags,
        metadata={"privacy_status": privacy_status},
    )


def _save_publish_results(
    request: PublishRequest,
    results: list[PublishResult],
) -> str:
    publish_state_path = save_publish_state(
        root_dir=config.root_dir,
        request=request,
        results=results,
    )
    logger.info(f"platform publish state saved: {publish_state_path}")
    return publish_state_path


def _make_skipped_publish_results(
    publishers: list[PlatformPublisher],
    status: str,
    reason: str,
    dry_run: bool = False,
    no_upload: bool = False,
) -> list[PublishResult]:
    return [
        PublishResult(
            platform=publisher.platform_name,
            success=True,
            status=status,
            error=reason,
            dry_run=dry_run,
            no_upload=no_upload,
        )
        for publisher in publishers
    ]


def _publisher_configuration_error(publisher: PlatformPublisher) -> str:
    error_getter = getattr(publisher, "configuration_error", None)
    if callable(error_getter):
        return str(error_getter())
    return f"{publisher.platform_name} publisher is not configured"


def _get_daily_voice_name() -> str:
    voice_names = config.app.get("daily_voice_names", [])
    if isinstance(voice_names, str):
        voice_names = [voice_names]
    voice_names = [str(name).strip() for name in voice_names if str(name).strip()]
    if not voice_names:
        return _get_config_value("daily_voice_name", "zh-CN-XiaoyiNeural-Female")

    now = datetime.now()
    slot = (now.toordinal() * 2) + (1 if now.hour >= 16 else 0)
    return voice_names[slot % len(voice_names)]


def _has_config_value(key: str) -> bool:
    value = config.app.get(key)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(value)


def _resolve_video_source() -> str:
    requested = str(_get_config_value("daily_video_source", config.app.get("video_source", "auto"))).strip().lower()
    if requested in {"auto", ""}:
        if _has_config_value("pexels_api_keys"):
            return "pexels"
        if _has_config_value("pixabay_api_keys"):
            return "pixabay"
        logger.warning("no Pexels/Pixabay API key configured; falling back to local test materials")
        return "local"

    if requested == "pexels" and not _has_config_value("pexels_api_keys"):
        logger.warning("daily_video_source=pexels but pexels_api_keys is empty; falling back to local")
        return "local"
    if requested == "pixabay" and not _has_config_value("pixabay_api_keys"):
        logger.warning("daily_video_source=pixabay but pixabay_api_keys is empty; falling back to local")
        return "local"

    return requested


def _prepare_local_materials() -> list[MaterialInfo]:
    local_videos_dir = Path(config.root_dir) / "storage" / "local_videos"
    local_videos_dir.mkdir(parents=True, exist_ok=True)

    bundled_resources_dir = Path(config.root_dir) / "test" / "resources"
    bundled_image_paths = sorted(bundled_resources_dir.glob("*.png"))
    if not bundled_image_paths:
        bundled_image_paths = sorted(bundled_resources_dir.glob("*.mp4"))

    if not bundled_image_paths:
        return []

    materials: list[MaterialInfo] = []
    for source_path in bundled_image_paths:
        target_path = local_videos_dir / source_path.name
        if not target_path.exists():
            shutil.copyfile(source_path, target_path)
        materials.append(MaterialInfo(url=target_path.name))

    return materials


DEFAULT_DAILY_MATERIAL_TERMS = [
    "technology news",
    "digital technology",
    "computer chip",
    "data center",
    "city skyline",
]

DAILY_MATERIAL_KEYWORD_RULES = [
    (
        (
            "ai",
            "gemini",
            "openai",
            "chatgpt",
            "\u4eba\u5de5\u667a\u6167",
            "\u751f\u6210\u5f0fai",
        ),
        ("artificial intelligence", "machine learning", "data center"),
    ),
    (
        (
            "nvidia",
            "gpu",
            "rtx",
            "\u8f1d\u9054",
            "\u9ec3\u4ec1\u52f3",
        ),
        ("computer chip", "gpu processor", "technology conference"),
    ),
    (
        (
            "tsmc",
            "semiconductor",
            "\u53f0\u7a4d\u96fb",
            "\u534a\u5c0e\u9ad4",
            "\u6676\u7247",
        ),
        ("semiconductor factory", "computer chip", "circuit board"),
    ),
    (
        (
            "cyber",
            "security",
            "hacker",
            "\u8cc7\u5b89",
            "\u9ed1\u5ba2",
            "\u8a50\u9a19",
        ),
        ("cyber security", "hacker", "server room"),
    ),
    (
        (
            "iphone",
            "android",
            "smartphone",
            "\u624b\u6a5f",
            "\u61c9\u7528\u7a0b\u5f0f",
        ),
        ("smartphone", "mobile app", "people using phone"),
    ),
    (
        (
            "tesla",
            "ev",
            "\u96fb\u52d5\u8eca",
            "\u81ea\u99d5\u8eca",
        ),
        ("electric car", "autonomous vehicle", "battery technology"),
    ),
    (
        (
            "spacex",
            "rocket",
            "satellite",
            "\u592a\u7a7a",
            "\u885b\u661f",
        ),
        ("space technology", "rocket launch", "satellite"),
    ),
    (
        (
            "robot",
            "robotics",
            "\u6a5f\u5668\u4eba",
            "\u81ea\u52d5\u5316",
        ),
        ("robotics", "factory automation", "industrial robot"),
    ),
    (
        (
            "gaming",
            "esports",
            "faker",
            "\u96fb\u7af6",
            "\u904a\u6232",
        ),
        ("gaming computer", "esports arena", "computer hardware"),
    ),
]


def _has_cjk(text: str) -> bool:
    """Return True if *text* contains any CJK (Chinese/Japanese/Korean) character."""
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text or ""))


def _ensure_english_material_term(term: str) -> str:
    """
    Guarantee the term is Pexels-searchable (ASCII only).

    * Pure-ASCII terms pass through unchanged.
    * CJK terms are looked up in ``llm.STOCK_VIDEO_KEYWORD_MAP``.
      On a hit the mapped English phrase is returned.
    * Unmapped CJK terms log a warning and return "" so callers can skip them.
    """
    if not _has_cjk(term):
        return term  # already English-safe

    from app.services.llm import STOCK_VIDEO_KEYWORD_MAP

    term_lower = term.lower()
    for keywords, english_term in STOCK_VIDEO_KEYWORD_MAP:
        if any(kw.lower() in term_lower for kw in keywords):
            logger.debug(
                f"material term {term!r} mapped to English: {english_term!r}"
            )
            return english_term

    logger.warning(
        f"material term {term!r} contains CJK characters and has no English mapping; "
        "it will be skipped — add an English equivalent to daily_material_fallback_terms"
    )
    return ""


def _normalize_material_term(term: str) -> str:
    term = re.sub(r"[^A-Za-z0-9 -]+", " ", term or "")
    term = re.sub(r"\s+", " ", term).strip().lower()
    if not term:
        return ""
    words = term.split()
    if len(words) > 3:
        term = " ".join(words[:3])
    return term


def _append_material_terms(
    target: list[str],
    candidates: list[str] | tuple[str, ...],
    amount: int,
) -> None:
    for candidate in candidates:
        # Ensure English before normalising — Pexels only accepts ASCII keywords
        english = _ensure_english_material_term(candidate)
        if not english:
            continue
        term = _normalize_material_term(english)
        if term and term not in target:
            target.append(term)
        if len(target) >= amount:
            return


def _build_daily_material_terms(entry, title: str, full_text: str = "") -> list[str]:
    amount = int(_get_config_value("daily_material_term_count", 5))
    amount = max(1, min(amount, 8))
    text = f"{title} {entry.title} {entry.summary} {full_text}".lower()

    terms: list[str] = []
    for keywords, mapped_terms in DAILY_MATERIAL_KEYWORD_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            _append_material_terms(terms, mapped_terms, amount)

    fallback_terms = _get_config_list("daily_material_fallback_terms")
    if not fallback_terms:
        fallback_terms = DEFAULT_DAILY_MATERIAL_TERMS
    _append_material_terms(terms, fallback_terms, amount)
    return terms


def _get_video_duration(video_path: str) -> float:
    clip = None
    try:
        clip = video_service._open_video_clip_quietly(video_path, audio=False)
        return float(getattr(clip, "duration", 0.0) or 0.0)
    finally:
        video_service.close_clip(clip)


def _count_cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def _has_balanced_quotes(text: str) -> bool:
    pairs = [("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’")]
    return all(text.count(left) == text.count(right) for left, right in pairs)


def _ends_with_sentence_punctuation(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    value = value.rstrip("」』”’\"'")
    return bool(value) and value[-1] in "。？！!?"


def _get_terminal_fragment_patterns() -> list[str]:
    configured = _get_config_list("daily_quality_gate_terminal_fragments")
    if configured:
        return configured
    return [
        "這代表著",
        "這意味著",
        "也就是說",
        "換句話說",
        "但其實",
        "但現實是",
        "但接下來",
        "說他真的被爸媽「唸了一",
        "活下來",
        "爬完象山後",
        "原本以為",
        "不得不重新評估",
        "接下來",
    ]


def _run_script_quality_gate(result: dict) -> list[str]:
    script = str(result.get("script", "") or "").strip()
    if not script:
        return ["script is missing"]

    issues: list[str] = []
    min_cjk_chars = int(_get_config_value("daily_quality_gate_min_script_cjk_chars", 250))
    cjk_chars = _count_cjk_chars(script)
    if cjk_chars < min_cjk_chars:
        issues.append(f"script is too short: {cjk_chars} CJK chars")

    min_audio_seconds = float(
        _get_config_value(
            "daily_quality_gate_min_audio_seconds",
            _get_config_value("daily_quality_gate_min_duration_seconds", 35),
        )
    )
    audio_duration = float(result.get("audio_duration", 0) or 0)
    if audio_duration and audio_duration < min_audio_seconds:
        issues.append(f"audio duration is too short: {audio_duration:.1f}s")

    if not _ends_with_sentence_punctuation(script):
        issues.append("script does not end with sentence punctuation")

    if not _has_balanced_quotes(script):
        issues.append("script has unbalanced quotes")

    for fragment in _get_terminal_fragment_patterns():
        if fragment and script.endswith(fragment):
            issues.append(f"script ends with incomplete fragment: {fragment}")
            break

    return issues


def _run_quality_gate(
    result: dict,
    video_path: str,
    title: str,
    description: str,
    params: VideoParams,
) -> list[str]:
    if not _get_config_bool("daily_quality_gate_enabled", True):
        return []

    issues: list[str] = []
    issues.extend(_run_script_quality_gate(result))

    if not title.strip():
        issues.append("title is empty")
    if len(title.strip()) > int(_get_config_value("daily_quality_gate_max_title_length", 100)):
        issues.append("title is too long")
    if not description.strip():
        issues.append("description is empty")

    if not os.path.isfile(video_path):
        issues.append(f"video file not found: {video_path}")
    else:
        min_size = int(_get_config_value("daily_quality_gate_min_video_bytes", 100_000))
        file_size = os.path.getsize(video_path)
        if file_size < min_size:
            issues.append(f"video file is too small: {file_size} bytes")

        try:
            duration = _get_video_duration(video_path)
            min_duration = float(_get_config_value("daily_quality_gate_min_duration_seconds", 35))
            max_duration = float(_get_config_value("daily_quality_gate_max_duration_seconds", 180))
            if duration <= 0:
                issues.append("video duration is unavailable")
            elif duration < min_duration:
                issues.append(f"video duration is too short: {duration:.1f}s")
            elif duration > max_duration:
                issues.append(f"video duration is too long: {duration:.1f}s")
        except Exception as exc:
            issues.append(f"failed to inspect video duration: {exc}")

    subtitle_required = _get_config_bool("daily_quality_gate_require_subtitle", True)
    if subtitle_required and params.subtitle_enabled:
        subtitle_path = str(result.get("subtitle_path", "") or "")
        if not subtitle_path or not os.path.isfile(subtitle_path):
            issues.append("subtitle file is missing")
        elif os.path.getsize(subtitle_path) <= 0:
            issues.append("subtitle file is empty")

    if params.video_source != "local":
        materials = result.get("materials", [])
        if not isinstance(materials, list) or not materials:
            issues.append("downloaded video materials are missing")

    return issues


@dataclasses.dataclass
class _JobContext:
    """Holds the fields that are constant for the entire run() execution.

    Call .save(**overrides) instead of repeating all 17 parameters of
    _save_job_metadata at every early-exit or success path.
    """

    task_id: str
    entry_id: str
    title: str
    description: str
    prompt: str
    privacy_status: str = ""
    video_source: str = ""
    voice_name: str = ""
    material_terms: list[str] | None = None

    def save(
        self,
        *,
        video_path: str = "",
        upload_video_id: str = "",
        success: bool = True,
        error: str = "",
        dry_run: bool = False,
        no_upload: bool = False,
        failure_stage: str = "",
        warnings: list[str] | None = None,
        quality_issues: list[str] | None = None,
        publish_state_path: str = "",
        platform_results: list[dict] | None = None,
    ) -> str:
        """Delegate to _save_job_metadata with the fixed fields pre-filled."""
        return _save_job_metadata(
            task_id=self.task_id,
            entry_id=self.entry_id,
            title=self.title,
            description=self.description,
            prompt=self.prompt,
            privacy_status=self.privacy_status,
            video_source=self.video_source,
            voice_name=self.voice_name,
            material_terms=self.material_terms,
            video_path=video_path,
            upload_video_id=upload_video_id,
            success=success,
            error=error,
            dry_run=dry_run,
            no_upload=no_upload,
            failure_stage=failure_stage,
            warnings=warnings,
            quality_issues=quality_issues,
            publish_state_path=publish_state_path,
            platform_results=platform_results,
        )


def _save_job_metadata(
    task_id: str,
    entry_id: str,
    title: str,
    description: str,
    prompt: str,
    video_path: str = "",
    upload_video_id: str = "",
    success: bool = True,
    error: str = "",
    dry_run: bool = False,
    no_upload: bool = False,
    privacy_status: str = "",
    video_source: str = "",
    voice_name: str = "",
    material_terms: list[str] | None = None,
    failure_stage: str = "",
    warnings: list[str] | None = None,
    quality_issues: list[str] | None = None,
    publish_state_path: str = "",
    platform_results: list[dict] | None = None,
) -> str:
    """Write a JSON metadata file per execution for audit / review."""
    jobs_dir = Path(config.root_dir) / "storage" / "auto_publish" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    job_data = {
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry_id": entry_id,
        "title": title,
        "description": description,
        "prompt": prompt,
        "video_path": video_path,
        "upload_video_id": upload_video_id,
        "success": success,
        "error": error,
        "dry_run": dry_run,
        "no_upload": no_upload,
        "privacy_status": privacy_status,
        "video_source": video_source,
        "voice_name": voice_name,
        "material_terms": material_terms or [],
        "failure_stage": failure_stage,
        "warnings": warnings or [],
        "quality_issues": quality_issues or [],
        "publish_state_path": publish_state_path,
        "platform_results": platform_results or [],
    }

    job_file = jobs_dir / f"{task_id}.json"
    with open(job_file, "w", encoding="utf-8") as f:
        json.dump(job_data, f, ensure_ascii=False, indent=2)

    logger.info(f"job metadata saved: {job_file}")
    return str(job_file)



# ──────────────────────────────────────────────────────────────────────
# Pending-upload helpers  (cross-run recovery when upload fails)
# ──────────────────────────────────────────────────────────────────────

_PENDING_UPLOAD_TTL_HOURS: int = 72


def _pending_upload_path() -> str:
    return str(Path(config.root_dir) / "storage" / "auto_publish" / "pending_upload.json")


def _save_pending_upload(publish_request: PublishRequest, privacy_status: str) -> None:
    """Persist the upload payload so the next run can retry if this run's upload fails."""
    path = _pending_upload_path()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_PENDING_UPLOAD_TTL_HOURS)
    data = {
        "task_id": publish_request.task_id,
        "entry_id": publish_request.entry_id,
        "video_path": publish_request.video_path,
        "title": publish_request.title,
        "description": publish_request.description,
        "source_url": publish_request.source_url,
        "source_name": publish_request.source_name,
        "summary": publish_request.summary,
        "hashtags": list(publish_request.hashtags),
        "privacy_status": privacy_status,
        "saved_at": now.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    logger.info(
        f"pending upload saved "
        f"(expires {expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')}): {path}"
    )


def _load_pending_upload() -> dict | None:
    """Load the pending upload file; return None if absent, expired, or video missing."""
    path = _pending_upload_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning(f"failed to read pending upload file, ignoring: {exc}")
        return None

    expires_str = data.get("expires_at", "")
    if expires_str:
        try:
            expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                logger.warning(f"pending upload expired at {expires_str}; discarding")
                _clear_pending_upload()
                return None
        except ValueError:
            pass

    video_path = data.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        logger.warning(f"pending upload video not found: {video_path!r}; discarding")
        _clear_pending_upload()
        return None

    return data


def _clear_pending_upload() -> None:
    """Remove the pending upload file after a successful upload or expiry."""
    path = _pending_upload_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info(f"pending upload cleared: {path}")
    except Exception as exc:
        logger.warning(f"could not clear pending upload file: {exc}")


def _try_resume_pending_upload(
    publishers: list[PlatformPublisher],
    args: argparse.Namespace,
) -> bool:
    """
    If a pending upload exists from a previous failed run, retry it now.

    Returns:
        True  — no pending found, or pending upload succeeded;
                caller should continue with the normal RSS / generate flow.
        False — pending upload retry failed again;
                caller should abort to avoid stacking failures.
    """
    pending = _load_pending_upload()
    if pending is None:
        return True  # nothing to resume

    task_id = pending["task_id"]
    video_path = pending["video_path"]
    title = pending.get("title", "")
    privacy_status = pending.get("privacy_status", "private")

    logger.info(f"found pending upload — task_id={task_id}, title={title!r}")
    logger.info(f"resuming upload from: {video_path}")

    publish_request = _make_publish_request(
        task_id=task_id,
        entry_id=pending.get("entry_id", ""),
        video_path=video_path,
        title=title,
        description=pending.get("description", ""),
        source_url=pending.get("source_url", ""),
        source_name=pending.get("source_name", ""),
        summary=pending.get("summary", ""),
        hashtags=pending.get("hashtags", []),
        privacy_status=privacy_status,
    )

    if args.no_upload:
        logger.info("--no-upload: skipping pending upload retry, continuing normal flow")
        return True

    platform_results: list[PublishResult] = []
    for publisher in publishers:
        if not publisher.is_configured():
            logger.warning(
                f"pending upload: {publisher.platform_name} not configured, skipping"
            )
            continue
        result = publisher.publish(publish_request)
        platform_results.append(result)
        if not result.success:
            logger.error(
                f"pending upload retry failed ({publisher.platform_name}): {result.error}"
            )
            _save_publish_results(publish_request, platform_results)
            notification_service.notify_failure(
                NotificationContext(
                    task_id=task_id,
                    title=title,
                    stage="pending_upload_retry",
                    error=result.error or f"{publisher.platform_name} upload failed",
                )
            )
            return False  # keep pending file; abort this run

    if not platform_results:
        # All publishers unconfigured; clear pending and continue
        logger.warning(
            "pending upload: no configured publishers; clearing pending and continuing"
        )
        _clear_pending_upload()
        return True

    # All publishers succeeded ─────────────────────────────────────────
    entry_id = pending.get("entry_id", "")
    if entry_id:
        state_file = _get_state_file()
        existing_seen = load_seen_entries(state_file)
        existing_seen.add(entry_id)
        save_seen_entries(state_file, existing_seen)
        logger.info(f"pending entry marked as seen: {entry_id}")

    _clear_pending_upload()
    publish_state_path = _save_publish_results(publish_request, platform_results)

    youtube_result = next(
        (r for r in platform_results if r.platform == "youtube" and r.success), None
    )
    youtube_video_id = youtube_result.remote_id if youtube_result else ""

    if youtube_video_id:
        thumb_path = os.path.join(
            os.path.dirname(video_path), f"thumbnail-{task_id}-resume.jpg"
        )
        thumb_result = generate_thumbnail(title=title, output_path=thumb_path)
        if thumb_result:
            youtube_uploader.upload_thumbnail(
                video_id=youtube_video_id, thumbnail_path=thumb_result
            )

    notification_service.notify_success(
        NotificationContext(
            task_id=task_id,
            title=title,
            youtube_video_id=youtube_video_id,
            privacy_status=privacy_status,
            video_source="",
            job_path=publish_state_path,
        )
    )
    logger.success(
        f"pending upload recovered — task_id={task_id}, title={title!r}; "
        "continuing with normal RSS/generate flow"
    )
    return True  # pending done; continue with normal flow


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch an RSS item, generate a short video, and upload to YouTube."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch feeds, select candidate, build prompt, and stop before generating video or uploading.",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Generate the video but skip uploading to YouTube.",
    )
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default=None,
        help="Override the YouTube upload privacy status.",
    )
    parser.add_argument(
        "--publish-platforms",
        "--platforms",
        default="",
        help=(
            "Comma-separated platforms to publish to. "
            "Supported: youtube, instagram_reels, facebook_reels. "
            "Defaults to daily_publish_platforms in config.toml."
        ),
    )
    return parser.parse_args()


def run() -> int:
    # CLI mode has no WebUI progress consumer; discard all state updates silently.
    _state_module.use_null_state()

    args = _parse_args()
    task_id = str(uuid4())
    publish_platforms = _get_publish_platforms(args.publish_platforms)
    try:
        publishers = _get_publishers(publish_platforms)
    except ValueError as exc:
        error = str(exc)
        logger.error(error)
        # entry_id/title/description/prompt not yet known — use bare function
        job_path = _save_job_metadata(
            task_id=task_id,
            entry_id="",
            title="",
            description="",
            prompt="",
            success=False,
            error=error,
            failure_stage="platform_config",
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                stage="platform_config",
                error=error,
                job_path=job_path,
            )
        )
        return 1
    logger.info(f"publish platforms: {', '.join(publish_platforms)}")

    # Retry any pending upload from a previous failed run before starting the normal flow
    if not _try_resume_pending_upload(publishers, args):
        return 1

    feed_urls = _get_feed_urls()
    if not feed_urls:
        error = "no RSS feeds configured; set daily_rss_feeds in config.toml"
        logger.error(error)
        # entry/title/description/prompt not yet known — use bare function
        job_path = _save_job_metadata(
            task_id=task_id,
            entry_id="",
            title="",
            description="",
            prompt="",
            success=False,
            error=error,
            failure_stage="rss_config",
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                stage="rss_config",
                error=error,
                job_path=job_path,
            )
        )
        return 1

    state_file = _get_state_file()
    seen_entries = load_seen_entries(state_file)
    candidate_count = int(_get_config_value("daily_candidate_count", 5))
    focus_keywords = _get_config_list("daily_focus_keywords")
    focus_bonus = int(_get_config_value("daily_focus_keyword_bonus", 8))
    candidates = collect_candidate_entries(feed_urls, seen_entries, limit=candidate_count)
    if candidates:
        logger.info(f"collected {len(candidates)} feed candidates")
        for index, candidate in enumerate(candidates, start=1):
            logger.info(f"candidate #{index}: {candidate.title}")

    if not candidates:
        logger.info("no new feed items found")
        return 0

    privacy_status = args.privacy or _get_config_value("youtube_upload_privacy_status", "private")
    video_source = _resolve_video_source()
    min_summary_length = int(_get_config_value("daily_min_summary_length", 80))
    min_full_text_length = int(_get_config_value("daily_min_full_text_length", 300))

    entry = None
    full_text = ""
    remaining_candidates = list(candidates)
    skipped_context_issues: list[str] = []
    while remaining_candidates:
        selected_entry = select_best_entry_for_video(
            remaining_candidates,
            focus_keywords=focus_keywords,
            focus_bonus=focus_bonus,
        )
        if selected_entry is None:
            break

        logger.info(f"selected feed item: {selected_entry.title}")
        logger.info(f"fetching full article text from: {selected_entry.link}")
        selected_full_text = fetch_article_text(selected_entry.link)
        if selected_full_text:
            logger.info(f"full article text fetched: {len(selected_full_text)} chars")
        else:
            logger.warning("full article text unavailable, will use RSS summary only")

        source_context = describe_source_context(
            selected_entry,
            full_text=selected_full_text,
            min_summary_length=min_summary_length,
            min_full_text_length=min_full_text_length,
        )
        logger.info(f"source context profile: {source_context}")
        if has_enough_source_context(
            selected_entry,
            full_text=selected_full_text,
            min_summary_length=min_summary_length,
            min_full_text_length=min_full_text_length,
        ):
            entry = selected_entry
            full_text = selected_full_text
            break

        issue = (
            f"{selected_entry.title}: "
            f"summary={len(selected_entry.summary.strip())} chars, "
            f"full_text={len((selected_full_text or '').strip())} chars, "
            f"profile={source_context}"
        )
        logger.warning(f"skip candidate with insufficient source context: {issue}")
        skipped_context_issues.append(issue)
        remaining_candidates = [
            candidate
            for candidate in remaining_candidates
            if candidate.entry_id != selected_entry.entry_id
        ]

    if entry is None:
        error = "no usable feed item found after source-context filtering"
        if skipped_context_issues:
            error += ": " + "; ".join(skipped_context_issues[:3])
        logger.error(error)
        # entry not yet selected — title/description/prompt unknown; use bare function
        job_path = _save_job_metadata(
            task_id=task_id,
            entry_id="",
            title="",
            description="",
            prompt="",
            success=False,
            error=error,
            privacy_status=privacy_status,
            video_source=video_source,
            failure_stage="source_context",
            quality_issues=[error],
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                title="",
                stage="source_context",
                error=error,
                job_path=job_path,
            )
        )
        return 1

    prompt = build_script_prompt(
        entry,
        full_text=full_text,
        min_full_text_length=min_full_text_length,
    )
    title = generate_video_title(
        entry,
        title_prefix=_get_config_value("daily_video_title_prefix", ""),
        title_suffix=_get_config_value("daily_video_title_suffix", ""),
        max_length=int(_get_config_value("daily_video_title_max_length", 90)),
    )
    description_template = _get_config_value(
        "youtube_description_template",
        "來源：{source}\n連結：{url}\n\n{summary}\n",
    )
    summary = entry.summary or entry.title
    description = description_template.format(
        title=title,
        source=entry.feed_url,
        url=entry.link,
        summary=summary,
        published=entry.published,
        prompt=prompt,
    )
    publish_hashtags = _get_config_list("daily_publish_hashtags") or _get_config_list("youtube_upload_tags")
    draft_publish_request = _make_publish_request(
        task_id=task_id,
        entry_id=entry.entry_id,
        video_path="",
        title=title,
        description=description,
        source_url=entry.link,
        source_name=entry.feed_url,
        summary=summary,
        hashtags=publish_hashtags,
        privacy_status=privacy_status,
    )
    selected_voice_name = _get_daily_voice_name()
    material_terms = [] if video_source == "local" else _build_daily_material_terms(
        entry,
        title=title,
        full_text=full_text,
    )
    logger.info(f"voice_name: {selected_voice_name}")
    if material_terms:
        logger.info(f"stock video search terms: {material_terms}")

    # Build the shared job context — all call sites below use job_ctx.save()
    job_ctx = _JobContext(
        task_id=task_id,
        entry_id=entry.entry_id,
        title=title,
        description=description,
        prompt=prompt,
        privacy_status=privacy_status,
        video_source=video_source,
        voice_name=selected_voice_name,
        material_terms=material_terms,
    )

    # ---------- dry-run: stop here ----------
    if args.dry_run:
        logger.info("--- DRY RUN ---")
        logger.info(f"task_id:     {task_id}")
        logger.info(f"title:       {title}")
        logger.info(f"privacy:     {privacy_status}")
        logger.info(f"video_source:{video_source}")
        logger.info(f"voice_name:  {selected_voice_name}")
        logger.info(f"terms:       {material_terms}")
        logger.info(f"description:\n{description}")
        logger.info(f"prompt:\n{prompt}")
        dry_results = _make_skipped_publish_results(
            publishers=publishers,
            status="dry_run",
            reason="--dry-run before video generation",
            dry_run=True,
        )
        publish_state_path = _save_publish_results(draft_publish_request, dry_results)
        job_ctx.save(
            dry_run=True,
            publish_state_path=publish_state_path,
            platform_results=publish_results_to_dicts(dry_results),
        )
        return 0

    # ---------- generate video ----------
    params = VideoParams(
        video_subject=title,
        video_script="",
        video_aspect=VideoAspect.portrait.value,
        video_count=1,
        video_source=video_source,
        video_terms=material_terms if video_source != "local" else None,
        voice_name=selected_voice_name,
        voice_rate=float(_get_config_value("daily_voice_rate", 1.0)),
        bgm_type=_get_config_value("daily_bgm_type", "random"),
        subtitle_enabled=bool(_get_config_value("daily_subtitle_enabled", True)),
        paragraph_number=int(_get_config_value("daily_paragraph_number", 1)),
        video_script_prompt=prompt,
        custom_system_prompt=_get_config_value(
            "daily_custom_system_prompt",
            "You write concise, factual scripts for a YouTube Shorts video.",
        ),
        video_materials=_prepare_local_materials() if video_source == "local" else None,
    )

    result = task.start(task_id, params, stop_at="video")
    if not result:
        error = "video generation failed"
        logger.error(error)
        job_path = job_ctx.save(
            success=False,
            error=error,
            failure_stage="video_generation",
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                title=title,
                stage="video_generation",
                error=error,
                job_path=job_path,
            )
        )
        return 1

    videos = result.get("videos", []) if isinstance(result, dict) else []
    if not videos:
        error = "no generated videos returned"
        logger.error("no generated videos returned from task")
        job_path = job_ctx.save(
            success=False,
            error=error,
            failure_stage="video_generation",
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                title=title,
                stage="video_generation",
                error=error,
                job_path=job_path,
            )
        )
        return 1

    video_path = videos[0]

    quality_issues = _run_quality_gate(
        result=result,
        video_path=video_path,
        title=title,
        description=description,
        params=params,
    )
    if quality_issues:
        error = "; ".join(quality_issues)
        logger.error(f"quality gate failed: {error}")
        job_path = job_ctx.save(
            video_path=video_path,
            success=False,
            error=error,
            failure_stage="quality_gate",
            quality_issues=quality_issues,
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                title=title,
                stage="quality_gate",
                error=error,
                job_path=job_path,
            )
        )
        return 1

    publish_request = _make_publish_request(
        task_id=task_id,
        entry_id=entry.entry_id,
        video_path=video_path,
        title=title,
        description=description,
        source_url=entry.link,
        source_name=entry.feed_url,
        summary=summary,
        hashtags=publish_hashtags,
        privacy_status=privacy_status,
    )

    # ---------- no-upload or upload not configured ----------
    if args.no_upload:
        reason = "--no-upload flag"
        logger.warning(f"upload skipped ({reason}); video saved at: {video_path}")
        no_upload_results = _make_skipped_publish_results(
            publishers=publishers,
            status="skipped",
            reason=reason,
            no_upload=True,
        )
        publish_state_path = _save_publish_results(publish_request, no_upload_results)
        job_ctx.save(
            video_path=video_path,
            no_upload=True,
            publish_state_path=publish_state_path,
            platform_results=publish_results_to_dicts(no_upload_results),
        )
        return 0

    config_errors = [
        PublishResult(
            platform=publisher.platform_name,
            success=False,
            status="not_configured",
            error=_publisher_configuration_error(publisher),
        )
        for publisher in publishers
        if not publisher.is_configured()
    ]
    if config_errors:
        error = "; ".join(result.error for result in config_errors)
        logger.error(error)
        publish_state_path = _save_publish_results(publish_request, config_errors)
        failure_stage = (
            "youtube_config"
            if len(config_errors) == 1 and config_errors[0].platform == "youtube"
            else "platform_config"
        )
        job_path = job_ctx.save(
            video_path=video_path,
            success=False,
            error=error,
            failure_stage=failure_stage,
            publish_state_path=publish_state_path,
            platform_results=publish_results_to_dicts(config_errors),
        )
        notification_service.notify_failure(
            NotificationContext(
                task_id=task_id,
                title=title,
                stage=failure_stage,
                error=error,
                job_path=job_path,
            )
        )
        return 1

    # ---------- publish ----------
    # Persist the upload payload now so the next scheduled run can retry
    # without re-generating the video if the upload below fails.
    _save_pending_upload(publish_request, privacy_status)

    platform_results: list[PublishResult] = []
    publish_state_path = ""
    for publisher in publishers:
        result = publisher.publish(publish_request)
        platform_results.append(result)
        publish_state_path = _save_publish_results(publish_request, platform_results)
        if not result.success:
            if any(item.success and item.status == "published" for item in platform_results):
                seen_entries.add(entry.entry_id)
                save_seen_entries(state_file, seen_entries)
            logger.error(f"{result.platform} publish failed: {result.error}")
            failure_stage = f"{result.platform}_publish"
            error = result.error or f"{result.platform} publish failed"
            job_path = job_ctx.save(
                video_path=video_path,
                success=False,
                error=error,
                failure_stage=failure_stage,
                publish_state_path=publish_state_path,
                platform_results=publish_results_to_dicts(platform_results),
            )
            notification_service.notify_failure(
                NotificationContext(
                    task_id=task_id,
                    title=title,
                    stage=failure_stage,
                    error=error,
                    job_path=job_path,
                )
            )
            return 1

    if any(result.success and result.status == "published" for result in platform_results):
        seen_entries.add(entry.entry_id)
        save_seen_entries(state_file, seen_entries)
        _clear_pending_upload()  # upload succeeded; remove the pending file

    youtube_result = next(
        (result for result in platform_results if result.platform == "youtube" and result.success),
        None,
    )
    youtube_video_id = youtube_result.remote_id if youtube_result else ""
    published_summary = ", ".join(
        f"{result.platform}:{result.remote_id or result.status}" for result in platform_results
    )
    logger.success(f"completed daily publish: {published_summary}")

    # ---------- generate & upload thumbnail ----------
    warnings: list[str] = []
    if youtube_video_id:
        thumb_path = os.path.join(
            os.path.dirname(video_path), f"thumbnail-{task_id}.jpg"
        )
        thumb_result = generate_thumbnail(title=title, output_path=thumb_path)
        if thumb_result:
            thumbnail_uploaded = youtube_uploader.upload_thumbnail(
                video_id=youtube_video_id,
                thumbnail_path=thumb_result,
            )
            if not thumbnail_uploaded:
                warnings.append("thumbnail upload failed")
        else:
            warnings.append("thumbnail generation failed")
            logger.warning("thumbnail generation failed; YouTube will use auto-generated frame")

    job_path = job_ctx.save(
        video_path=video_path,
        upload_video_id=youtube_video_id,
        warnings=warnings,
        publish_state_path=publish_state_path,
        platform_results=publish_results_to_dicts(platform_results),
    )

    for warning in warnings:
        notification_service.notify_warning(
            NotificationContext(
                task_id=task_id,
                title=title,
                youtube_video_id=youtube_video_id,
                stage="thumbnail",
                warning=warning,
                job_path=job_path,
            )
        )

    notification_service.notify_success(
        NotificationContext(
            task_id=task_id,
            title=title,
            youtube_video_id=youtube_video_id,
            privacy_status=privacy_status,
            video_source=video_source,
            job_path=job_path,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
