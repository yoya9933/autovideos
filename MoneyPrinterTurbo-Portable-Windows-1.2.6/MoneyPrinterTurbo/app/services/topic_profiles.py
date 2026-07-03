from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_TOPIC_PROFILE = "tech"


@dataclass(frozen=True)
class TopicProfile:
    name: str
    feed_urls: tuple[str, ...]
    candidate_count: int
    focus_keywords: tuple[str, ...]
    focus_bonus: int
    excluded_keywords: tuple[str, ...]
    editorial_brief: str


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def load_topic_profile(
    app_config: Mapping[str, Any],
    profile_name: str = "",
) -> TopicProfile:
    requested_name = str(
        profile_name
        or app_config.get("daily_default_topic_profile")
        or DEFAULT_TOPIC_PROFILE
    ).strip()
    raw_profiles = app_config.get("daily_topic_profiles")
    profiles = raw_profiles if isinstance(raw_profiles, Mapping) else {}
    raw_profile = profiles.get(requested_name)

    if raw_profile is None and requested_name != DEFAULT_TOPIC_PROFILE:
        raise ValueError(f"unknown topic profile: {requested_name}")
    if raw_profile is not None and not isinstance(raw_profile, Mapping):
        raise ValueError(f"invalid topic profile: {requested_name}")

    profile = raw_profile or {}
    use_legacy_defaults = requested_name == DEFAULT_TOPIC_PROFILE
    default_feeds = app_config.get("daily_rss_feeds", []) if use_legacy_defaults else []
    default_count = app_config.get("daily_candidate_count", 5) if use_legacy_defaults else 5
    default_keywords = app_config.get("daily_focus_keywords", []) if use_legacy_defaults else []
    default_bonus = app_config.get("daily_focus_keyword_bonus", 8) if use_legacy_defaults else 8

    return TopicProfile(
        name=requested_name,
        feed_urls=_string_tuple(profile.get("feeds", default_feeds)),
        candidate_count=max(1, int(profile.get("candidate_count", default_count))),
        focus_keywords=_string_tuple(profile.get("focus_keywords", default_keywords)),
        focus_bonus=int(profile.get("focus_keyword_bonus", default_bonus)),
        excluded_keywords=_string_tuple(profile.get("excluded_keywords", [])),
        editorial_brief=str(profile.get("editorial_brief", "")).strip(),
    )
