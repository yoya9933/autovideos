from __future__ import annotations

import html
import json
import os
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from loguru import logger


class _TextExtractor(HTMLParser):
    """Strip HTML tags; skip script/style/nav/footer noise; collect readable text."""

    _SKIP_TAGS = {
        "script", "style", "noscript", "head",
        "nav", "footer", "header", "aside", "iframe",
    }

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


class _MetadataExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_values: list[str] = []
        self.json_ld_values: list[str] = []
        self._capture_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs_dict = {str(key).lower(): str(value) for key, value in attrs if value is not None}
        if tag.lower() == "meta":
            name = attrs_dict.get("name", "").lower()
            prop = attrs_dict.get("property", "").lower()
            content = attrs_dict.get("content", "").strip()
            if content and (name in {"description", "twitter:description"} or prop == "og:description"):
                self.meta_values.append(content)
        elif tag.lower() == "script" and attrs_dict.get("type", "").lower() == "application/ld+json":
            self._capture_json_ld = True
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capture_json_ld:
            self._capture_json_ld = False
            value = "".join(self._json_ld_parts).strip()
            if value:
                self.json_ld_values.append(value)
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_json_ld:
            self._json_ld_parts.append(data)


def _iter_json_ld_objects(value):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_ld_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_objects(item)


def _extract_metadata_text(html_text: str) -> str:
    extractor = _MetadataExtractor()
    extractor.feed(html_text)

    parts: list[str] = []
    for raw_json_ld in extractor.json_ld_values:
        try:
            payload = json.loads(raw_json_ld)
        except json.JSONDecodeError:
            continue
        for item in _iter_json_ld_objects(payload):
            for key in ("articleBody", "description"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())

    parts.extend(extractor.meta_values)
    return _normalize_whitespace(" ".join(parts))


def _is_generic_article_text(text: str) -> bool:
    value = _normalize_whitespace(text).lower()
    generic_patterns = [
        "「google 新聞」匯集了世界各地的新聞來源",
        "google 新聞 匯集了世界各地的新聞來源",
        "google news brings together news sources",
        "google news aggregates",
    ]
    return any(pattern in value for pattern in generic_patterns)


_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_article_text(url: str, timeout: int = 15, max_length: int = 3000) -> str:
    """
    Fetch and return the plain-text body of an article at *url*.

    - Follows redirects (handles Google News short-links automatically).
    - Skips script / style / nav / footer noise via _TextExtractor.
    - Returns an empty string on any error so callers can fall back gracefully.
    - Caps output at *max_length* characters to keep LLM token cost low.
    """
    if not url:
        return ""
    try:
        response = requests.get(
            url,
            headers=_FETCH_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            logger.debug(f"fetch_article_text: non-HTML response ({content_type}) for {url}")
            return ""

        extractor = _TextExtractor()
        extractor.feed(response.text)
        text = _normalize_whitespace(extractor.get_text())
        metadata_text = _extract_metadata_text(response.text)
        if metadata_text and _is_generic_article_text(metadata_text):
            logger.debug("fetch_article_text: ignored generic metadata text")
            metadata_text = ""
        if len(metadata_text) > len(text):
            logger.info(
                f"fetch_article_text: using metadata article text ({len(metadata_text)} chars)"
            )
            text = metadata_text
        if text and _is_generic_article_text(text):
            logger.info("fetch_article_text: ignored generic article text")
            return ""

        if len(text) > max_length:
            text = text[:max_length].rstrip() + "..."

        logger.info(f"fetch_article_text: got {len(text)} chars from {url}")
        return text
    except Exception as exc:
        logger.warning(f"fetch_article_text failed ({url}): {exc}")
        return ""


ATOM_NS = "{http://www.w3.org/2005/Atom}"
DEFAULT_HEADERS = {
    "User-Agent": "MoneyPrinterTurbo/1.2.9 (+https://github.com/harry0703/MoneyPrinterTurbo)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}
LOW_INFORMATION_FEED_PATTERNS = [
    "trends.google.com",
    "google trends",
    "每日搜尋趨勢",
    "daily search trends",
]
EVENT_TITLE_ALIASES = {
    "輝達": "nvidia",
    "英偉達": "nvidia",
    "台積電": "tsmc",
    "臺積電": "tsmc",
    "人工智慧": "ai",
    "生成式ai": "ai",
}
STRONG_EVENT_ACTION_PATTERNS = [
    "直奔",
    "現身",
    "會見",
    "見",
    "合簽",
    "送",
    "抽",
    "拿",
    "推出",
    "宣告",
    "宣布",
    "啟動",
    "曝光",
    "爆料",
    "自爆",
    "點名",
    "回應",
    "警告",
    "遭",
    "跌剩",
    "走入歷史",
    "創下",
    "打破",
    "發表",
]
STRONG_EVENT_CONCRETE_PATTERNS = [
    "網咖",
    "顯卡",
    "粉絲",
    "basecamp",
    "faker",
    "nvidia",
    "rtx",
    "computex",
    "台積電",
    "輝達",
    "黃仁勳",
    "一中",
    "語資班",
    "學校",
    "韓國",
    "台灣",
    "t1",
    "iphone",
    "steam",
    "spacex",
]


@dataclass(frozen=True)
class FeedEntry:
    feed_url: str
    entry_id: str
    title: str
    summary: str
    link: str
    published: str = ""


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()


def _token_count(text: str) -> int:
    tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text or "")
    return len(tokens)


def _normalize_focus_keywords(focus_keywords: Iterable[str] | None) -> list[str]:
    if not focus_keywords:
        return []
    return [str(keyword).strip().lower() for keyword in focus_keywords if str(keyword).strip()]


def normalize_event_title(title: str) -> str:
    text = html.unescape(title or "").lower()
    text = re.sub(r"【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^\)]*\)", " ", text)
    text = re.sub(r"(快訊|獨家|更新|最新|懶人包|一次看|重點整理|新聞|報導)", " ", text)
    for alias, canonical in EVENT_TITLE_ALIASES.items():
        text = text.replace(alias, canonical)
    return "".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text))


def is_same_event_entry(
    left: FeedEntry,
    right: FeedEntry,
    similarity_threshold: float = 0.86,
) -> bool:
    if left.link and right.link and left.link == right.link:
        return True

    left_title = normalize_event_title(left.title)
    right_title = normalize_event_title(right.title)
    if not left_title or not right_title:
        return False
    if left_title == right_title:
        return True

    similarity = SequenceMatcher(None, left_title, right_title).ratio()
    return similarity >= similarity_threshold


def is_low_information_feed_entry(
    entry: FeedEntry,
    min_summary_length: int = 80,
) -> bool:
    text = f"{entry.feed_url} {entry.link}".lower()
    if any(pattern in text for pattern in LOW_INFORMATION_FEED_PATTERNS):
        return True

    title = entry.title.strip()
    summary = entry.summary.strip()
    if len(summary) >= min_summary_length:
        return False

    if not entry.link or entry.link == entry.feed_url:
        return True

    title_token_count = _token_count(title)
    if title_token_count <= 4 and len(summary) < min_summary_length:
        return True

    if re.fullmatch(r"[\w\u4e00-\u9fff\s｜|,/、，+-]{1,28}", title) and title_token_count <= 5:
        return True

    return False


def has_enough_source_context(
    entry: FeedEntry,
    full_text: str = "",
    min_summary_length: int = 80,
    min_full_text_length: int = 300,
    allow_strong_event_title: bool = True,
) -> bool:
    if len((full_text or "").strip()) >= min_full_text_length:
        return True
    if len(entry.summary.strip()) >= min_summary_length:
        return True
    if allow_strong_event_title and is_strong_event_title(entry):
        return True
    return False


def is_strong_event_title(entry: FeedEntry) -> bool:
    title = _normalize_whitespace(entry.title)
    summary = _normalize_whitespace(entry.summary)
    if not title or not entry.link or entry.link == entry.feed_url:
        return False

    if _token_count(title) < 12 or len(title) < 18:
        return False

    text = f"{title} {summary}".lower()
    if not any(pattern.lower() in text for pattern in STRONG_EVENT_ACTION_PATTERNS):
        return False

    concrete_score = 0
    concrete_score += min(2, len(re.findall(r"[A-Z][A-Za-z0-9]{2,}", title)))
    concrete_score += 1 if re.search(r"\d", title) else 0
    concrete_score += 1 if re.search(r"「[^」]{2,}」|『[^』]{2,}』", title) else 0
    concrete_score += sum(1 for pattern in STRONG_EVENT_CONCRETE_PATTERNS if pattern.lower() in text)

    return concrete_score >= 2


def describe_source_context(
    entry: FeedEntry,
    full_text: str = "",
    min_summary_length: int = 80,
    min_full_text_length: int = 300,
) -> str:
    if len((full_text or "").strip()) >= min_full_text_length:
        return "full_text"
    if len(entry.summary.strip()) >= min_summary_length:
        return "summary"
    if is_strong_event_title(entry):
        return "strong_event_title"
    return "insufficient"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    if not text.lstrip().startswith("<"):
        return text

    try:
        return " ".join(ET.fromstring(f"<root>{text}</root>").itertext())
    except ET.ParseError:
        return text


def _extract_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    text = "".join(element.itertext())
    return _normalize_whitespace(html.unescape(text))


def _extract_link(entry: ET.Element, feed_url: str) -> str:
    link = entry.findtext("link", default="").strip()
    if link:
        return urljoin(feed_url, link)

    for link_element in entry.findall(f"{ATOM_NS}link"):
        href = (link_element.attrib.get("href") or "").strip()
        rel = (link_element.attrib.get("rel") or "alternate").strip().lower()
        if href and rel in {"alternate", ""}:
            return urljoin(feed_url, href)

    return feed_url


def _entry_id(entry: ET.Element, link: str, title: str) -> str:
    guid = entry.findtext("guid", default="").strip()
    if guid:
        return guid

    atom_id = entry.findtext(f"{ATOM_NS}id", default="").strip()
    if atom_id:
        return atom_id

    return link or title


def _rss_entries(root: ET.Element, feed_url: str) -> list[FeedEntry]:
    items: list[FeedEntry] = []
    channel = root.find("channel")
    if channel is None:
        return items

    feed_title = _extract_text(channel.find("title"))
    for item in channel.findall("item"):
        title = _extract_text(item.find("title"))
        summary = _extract_text(item.find("description")) or _extract_text(item.find("summary"))
        link = _extract_link(item, feed_url)
        entry_id = _entry_id(item, link, title)
        published = _extract_text(item.find("pubDate"))
        if not title:
            continue

        items.append(
            FeedEntry(
                feed_url=feed_title or feed_url,
                entry_id=entry_id,
                title=title,
                summary=_normalize_whitespace(_strip_html(summary)) if summary else "",
                link=link,
                published=published,
            )
        )

    return items


def _atom_entries(root: ET.Element, feed_url: str) -> list[FeedEntry]:
    items: list[FeedEntry] = []
    feed_title = _extract_text(root.find(f"{ATOM_NS}title"))
    for entry in root.findall(f"{ATOM_NS}entry"):
        title = _extract_text(entry.find(f"{ATOM_NS}title"))
        summary = _extract_text(entry.find(f"{ATOM_NS}summary")) or _extract_text(entry.find(f"{ATOM_NS}content"))
        link = ""
        for link_element in entry.findall(f"{ATOM_NS}link"):
            href = (link_element.attrib.get("href") or "").strip()
            rel = (link_element.attrib.get("rel") or "alternate").strip().lower()
            if href and rel in {"alternate", ""}:
                link = urljoin(feed_url, href)
                break
        if not link:
            link = feed_url
        entry_id = _entry_id(entry, link, title)
        published = _extract_text(entry.find(f"{ATOM_NS}published")) or _extract_text(entry.find(f"{ATOM_NS}updated"))
        if not title:
            continue

        items.append(
            FeedEntry(
                feed_url=feed_title or feed_url,
                entry_id=entry_id,
                title=title,
                summary=_normalize_whitespace(_strip_html(summary)) if summary else "",
                link=link,
                published=published,
            )
        )

    return items


def fetch_feed_entries(feed_url: str, timeout: int = 30) -> list[FeedEntry]:
    response = requests.get(feed_url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    if root.tag.endswith("feed"):
        return _atom_entries(root, feed_url)
    return _rss_entries(root, feed_url)


def _parse_seen_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _load_seen_entry_records(state_file: str) -> dict[str, str]:
    if not os.path.isfile(state_file):
        return {}

    try:
        with open(state_file, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception as exc:
        logger.warning(f"failed to load feed state {state_file}: {exc}")
        return {}

    seen_entries = payload.get("seen_entries", [])
    if not isinstance(seen_entries, list):
        return {}

    records: dict[str, str] = {}
    for item in seen_entries:
        if isinstance(item, dict):
            entry_id = str(item.get("entry_id", "")).strip()
            seen_at = str(item.get("seen_at", "")).strip()
        else:
            entry_id = str(item).strip()
            seen_at = ""
        if entry_id:
            records[entry_id] = seen_at

    return records


def load_seen_entries(state_file: str, retention_days: int = 90) -> set[str]:
    records = _load_seen_entry_records(state_file)
    if not records:
        return set()

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    active_entries: set[str] = set()
    for entry_id, seen_at in records.items():
        seen_time = _parse_seen_at(seen_at)
        if seen_time is None or seen_time >= cutoff:
            active_entries.add(entry_id)

    return active_entries


def save_seen_entries(
    state_file: str,
    seen_entries: Iterable[str],
    limit: int = 300,
    retention_days: int = 90,
) -> None:
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    existing_records = _load_seen_entry_records(state_file)
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    cutoff = now - timedelta(days=retention_days)

    records: list[dict[str, str]] = []
    for entry_id in dict.fromkeys(str(item).strip() for item in seen_entries if str(item).strip()):
        seen_at = existing_records.get(entry_id) or now_text
        seen_time = _parse_seen_at(seen_at)
        if seen_time is not None and seen_time < cutoff:
            continue
        records.append({"entry_id": entry_id, "seen_at": seen_at})

    records.sort(key=lambda item: item["seen_at"] or "")
    payload = {
        "updated_at": now_text,
        "retention_days": retention_days,
        "seen_entries": records[-limit:],
    }
    with open(state_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def collect_candidate_entries(feed_urls: list[str], seen_entries: set[str], limit: int = 5) -> list[FeedEntry]:
    candidates: list[FeedEntry] = []
    for feed_url in feed_urls:
        try:
            entries = fetch_feed_entries(feed_url)
        except Exception as exc:
            logger.warning(f"failed to fetch feed {feed_url}: {exc}")
            continue

        for entry in entries:
            if entry.entry_id in seen_entries:
                continue
            if is_low_information_feed_entry(entry):
                logger.info(f"skip low-information feed entry: {entry.title}")
                continue
            if any(is_same_event_entry(entry, candidate) for candidate in candidates):
                logger.info(f"skip duplicate event feed entry: {entry.title}")
                continue
            candidates.append(entry)
            if len(candidates) >= limit:
                return candidates

    return candidates


def select_next_entry(feed_urls: list[str], seen_entries: set[str]) -> FeedEntry | None:
    candidates = collect_candidate_entries(feed_urls, seen_entries, limit=1)
    return candidates[0] if candidates else None


def _score_entry_for_video(
    entry: FeedEntry,
    focus_keywords: Iterable[str] | None = None,
    focus_bonus: int = 8,
) -> int:
    text = f"{entry.title} {entry.summary}".lower()
    score = 0

    if 8 <= len(entry.title) <= 80:
        score += 3
    if 80 <= len(entry.summary) <= 900:
        score += 4
    if entry.link and entry.link != entry.feed_url:
        score += 1
    if entry.published:
        score += 1
    if is_low_information_feed_entry(entry):
        score -= 20
    normalized_focus_keywords = _normalize_focus_keywords(focus_keywords)
    score += sum(focus_bonus for keyword in normalized_focus_keywords if keyword in text)

    strong_hooks = [
        "why",
        "how",
        "new",
        "first",
        "best",
        "breakthrough",
        "launch",
        "update",
        "study",
        "report",
        "ai",
        "為什麼",
        "怎麼",
        "首次",
        "第一",
        "最新",
        "突然",
        "爆紅",
        "突破",
        "震撼",
        "警告",
        "研究",
        "報告",
        "實測",
        "真相",
        "反轉",
        "關鍵",
        "影響",
        "改變",
        "生成式 ai",
        "人工智慧",
        "半導體",
        "資安",
        "詐騙",
        "健康",
        "太空",
        "心理",
    ]
    score += sum(2 for hook in strong_hooks if hook in text)

    weak_topics = ["live", "podcast", "newsletter", "活動預告", "直播", "徵才", "課程", "研討會", "優惠", "公告"]
    score -= sum(3 for topic in weak_topics if topic in text)

    return score


def _fallback_select_best_entry(
    entries: list[FeedEntry],
    focus_keywords: Iterable[str] | None = None,
    focus_bonus: int = 8,
) -> FeedEntry | None:
    if not entries:
        return None
    return max(entries, key=lambda entry: _score_entry_for_video(entry, focus_keywords, focus_bonus))


def _build_selection_prompt(entries: list[FeedEntry], focus_keywords: Iterable[str] | None = None) -> str:
    lines = [
        "你是繁體中文 YouTube Shorts 選題主編。請從候選 RSS 條目中，挑出最適合做成 45-75 秒爆款資訊短片的一篇。",
        "優先選擇：反直覺、有明確衝突、和多數人生活有關、有最新性、能用一句話講出懸念、能引發留言討論的題目。",
        "降低排序：純公告、活動預告、例行財報、過窄產業新聞、缺乏可解釋性的標題、只有搜尋關鍵字但沒有文章摘要的條目。",
        "只回覆被選中的序號數字，不要解釋。",
        "",
    ]
    normalized_focus_keywords = [str(keyword).strip() for keyword in focus_keywords or [] if str(keyword).strip()]
    if normalized_focus_keywords:
        lines.append(f"頻道聚焦主題：{', '.join(normalized_focus_keywords)}。相關題材可優先選。")
        lines.append("")
    lines.append("候選條目：")
    for index, entry in enumerate(entries, start=1):
        summary = entry.summary.strip()
        if len(summary) > 500:
            summary = summary[:500].rstrip() + "..."
        lines.append(
            f"{index}. 標題：{entry.title}\n"
            f"   來源：{entry.feed_url}\n"
            f"   發布：{entry.published or '未知'}\n"
            f"   摘要：{summary or entry.title}"
        )
    return "\n".join(lines)


def select_best_entry_for_video(
    entries: list[FeedEntry],
    focus_keywords: Iterable[str] | None = None,
    focus_bonus: int = 8,
) -> FeedEntry | None:
    if not entries:
        return None

    try:
        from app.services import llm

        response = llm._generate_response(_build_selection_prompt(entries, focus_keywords))
        match = re.search(r"\d+", response or "")
        if match:
            selected_index = int(match.group(0))
            if 1 <= selected_index <= len(entries):
                selected = entries[selected_index - 1]
                logger.info(f"AI selected feed candidate #{selected_index}: {selected.title}")
                return selected
        logger.warning(f"AI selection returned an invalid response: {response}")
    except Exception as exc:
        logger.warning(f"AI selection failed, falling back to local scoring: {exc}")

    selected = _fallback_select_best_entry(entries, focus_keywords, focus_bonus)
    if selected:
        logger.info(f"fallback selected feed candidate: {selected.title}")
    return selected


def build_script_prompt(
    entry: FeedEntry,
    full_text: str = "",
    max_summary_length: int = 1800,
    min_full_text_length: int = 300,
) -> str:
    """
    Build the LLM prompt for script generation.

    If *full_text* (fetched from the article URL) is available and longer than
    the RSS summary, it is used as the primary content source so the AI has
    richer material to work with.  The RSS summary is always shown as a
    fallback / cross-check reference.
    """
    summary = entry.summary.strip()
    if len(summary) > max_summary_length:
        summary = summary[:max_summary_length].rstrip() + "..."

    # Use whichever content source is richer
    full_text = (full_text or "").strip()
    if len(full_text) > max_summary_length:
        full_text = full_text[:max_summary_length].rstrip() + "..."

    has_full_article_context = len(full_text) >= min_full_text_length and len(full_text) > len(summary)
    if has_full_article_context:
        content_section = (
            f"文章全文（優先參考）：\n{full_text}\n\n"
            f"RSS 摘要（補充參考）：\n{summary or entry.title}\n"
        )
        logger.info("build_script_prompt: using full article text as primary source")
    else:
        content_section = f"摘要：\n{summary or entry.title}\n"
        logger.info("build_script_prompt: using RSS summary (full text unavailable or shorter)")

    target_duration = "45-75 秒" if has_full_article_context else "35-50 秒"
    target_length = "280-420 個中文字" if has_full_article_context else "250-320 個中文字"
    source_rule = (
        "只根據文章內容改寫，不逐字搬運，不補充來源沒有支持的細節。"
        if has_full_article_context
        else "只根據來源摘要與標題改寫；資訊不足時寧可縮短到 35-50 秒，不要湊字數，但一定要完整收束，不要補不存在的細節。"
    )

    return (
        f"請把以下 RSS 條目改寫成一支 {target_duration} 繁體中文 YouTube Shorts 旁白。\n"
        "內容策略：\n"
        "1. 前 3 秒必須直接出現重點、衝突、數字、風險或問題；第一句建議 18 個中文字以內，不要鋪陳背景。\n"
        "2. 第一句請從 5 種開頭公式中選 1 種：結果先講、數字衝擊、衝突對立、風險提醒、反常識。\n"
        "3. 範例方向：結果先講「AI 最大贏家，可能不是模型公司」；數字衝擊「一條產線，可能決定幾千億訂單」；衝突對立「公司花錢防駭，員工一封信就破功」；風險提醒「你沒被盜，不代表資料還安全」；反常識「晶片越小，風險反而越大」。\n"
        "4. 禁止使用「今天我們來聊」「最近」「你知道嗎」「隨著科技快速發展」「在這個數位時代」這類慢熱開場。\n"
        "5. 用「大家以為 A，但其實 B」或「看起來是小事，真正影響是 C」的結構製造轉折。\n"
        "6. 每 2-3 句要有一次推進：新資訊、原因、後果、對一般人的影響，避免流水帳。\n"
        "7. 口語、短句、可直接配音；不要新聞稿腔，不要教科書腔。\n"
        f"8. {source_rule}\n"
        f"9. 旁白長度必須落在 {target_length}，不要低於 250 個中文字。\n"
        "10. 最後一句必須是完整句子，並以「。」「？」「！」其中之一結尾；不要停在半句、不要留下未閉合引號。\n"
        "11. 不要輸出標題、分鏡、音效、hashtag、Markdown 或條列，只輸出旁白正文。\n\n"
        f"標題：{entry.title}\n"
        f"來源：{entry.feed_url}\n"
        f"網址：{entry.link}\n"
        f"發布時間：{entry.published or '未知'}\n\n"
        + content_section
    ).strip()


def _trim_title(title: str, max_length: int) -> str:
    title = _normalize_whitespace(title)
    if max_length <= 0 or len(title) <= max_length:
        return title
    return title[: max(1, max_length - 3)].rstrip(" ,，.。:：-") + "..."


def _clean_generated_title(title: str) -> str:
    lines = [line.strip() for line in (title or "").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return ""

    cleaned = lines[0]
    cleaned = re.sub(r"^\s*(?:\d+[\.\)、)]|[-*])\s*", "", cleaned)
    cleaned = re.sub(r"^(?:標題|片名|title)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"\s*#[\w\u4e00-\u9fff-]+", "", cleaned)
    cleaned = _normalize_whitespace(cleaned).strip(" \"'「」『』“”‘’")
    return _remove_unbalanced_title_quotes(cleaned)


def _remove_unbalanced_title_quotes(title: str) -> str:
    cleaned = title
    for left, right in [("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’")]:
        if cleaned.count(left) != cleaned.count(right):
            cleaned = cleaned.replace(left, "").replace(right, "")
    return cleaned.strip()


def build_title_prompt(entry: FeedEntry, max_summary_length: int = 1200) -> str:
    summary = entry.summary.strip()
    if len(summary) > max_summary_length:
        summary = summary[:max_summary_length].rstrip() + "..."

    return (
        "你是繁體中文 YouTube Shorts 標題編輯。請根據以下 RSS 條目，生成 1 個高點擊率但真實的影片標題。\n"
        "標題策略：\n"
        "1. 只使用來源標題與摘要能支持的資訊，不誇大、不捏造、不承諾來源沒有的結果。\n"
        "2. 優先使用反直覺、衝突、具體影響、問題句或懸念，但不能犧牲事實準確性。\n"
        "3. 18-34 個中文字優先，最長不要超過 60 個字。\n"
        "4. 不要新聞稿腔，不要來源名稱，不要 hashtag、emoji、引號或 Markdown。\n"
        "5. 只輸出標題本身，不要解釋或列多個選項。\n\n"
        f"原始標題：{entry.title}\n"
        f"來源：{entry.feed_url}\n"
        f"網址：{entry.link}\n"
        f"發布時間：{entry.published or '未知'}\n\n"
        f"摘要：\n{summary or entry.title}\n"
    ).strip()


def build_video_title(
    entry: FeedEntry,
    title_prefix: str = "",
    title_suffix: str = "",
    generated_title: str = "",
    max_length: int = 90,
) -> str:
    title = _remove_unbalanced_title_quotes((generated_title or entry.title).strip())
    if title_prefix:
        title = f"{title_prefix.strip()} {title}".strip()
    if title_suffix:
        title = f"{title} {title_suffix.strip()}".strip()
    return _trim_title(title, max_length)


def generate_video_title(
    entry: FeedEntry,
    title_prefix: str = "",
    title_suffix: str = "",
    max_length: int = 90,
) -> str:
    fallback_title = build_video_title(
        entry,
        title_prefix=title_prefix,
        title_suffix=title_suffix,
        max_length=max_length,
    )

    try:
        from app.services import llm

        response = llm._generate_response(build_title_prompt(entry))
        generated_title = _clean_generated_title(response or "")
        if generated_title:
            title = build_video_title(
                entry,
                title_prefix=title_prefix,
                title_suffix=title_suffix,
                generated_title=generated_title,
                max_length=max_length,
            )
            logger.info(f"AI generated video title: {title}")
            return title
        logger.warning(f"AI title generation returned an empty response: {response}")
    except Exception as exc:
        logger.warning(f"AI title generation failed, falling back to RSS title: {exc}")

    return fallback_title
