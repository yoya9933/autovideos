from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import urlparse


ERROR_TITLE_MARKERS = (
    "error:",
    "error：",
    "429",
    "quota",
    "rate limit",
    "rate_limit",
    "resource exhausted",
    "resource_exhausted",
)


@dataclass(frozen=True)
class DailyJobEntry:
    task_id: str
    timestamp: datetime | None
    title: str
    success: bool
    privacy_status: str
    upload_video_id: str
    failure_stage: str
    error: str
    source: str
    material_terms: tuple[str, ...] = field(default_factory=tuple)
    title_has_error: bool = False
    job_file: str = ""


@dataclass(frozen=True)
class DailyJobReport:
    report_date: date
    timezone_name: str
    entries: tuple[DailyJobEntry, ...]
    source_counts: Counter[str]
    material_term_counts: Counter[str]

    @property
    def total_jobs(self) -> int:
        return len(self.entries)

    @property
    def success_count(self) -> int:
        return sum(1 for entry in self.entries if entry.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for entry in self.entries if not entry.success)

    @property
    def public_upload_count(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.success and entry.privacy_status == "public" and entry.upload_video_id
        )

    @property
    def error_title_count(self) -> int:
        return sum(1 for entry in self.entries if entry.title_has_error)


def _timezone_for_name(timezone_name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except Exception:
        if timezone_name == "Asia/Taipei":
            return timezone(timedelta(hours=8), name="Asia/Taipei")
        return timezone.utc


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _title_has_error(title: str) -> bool:
    lowered = (title or "").lower()
    return any(marker in lowered for marker in ERROR_TITLE_MARKERS)


def _source_from_description(description: str) -> str:
    for line in (description or "").splitlines():
        if line.startswith("來源："):
            return line.split("：", 1)[1].strip()
        if line.lower().startswith("source:"):
            return line.split(":", 1)[1].strip()
    return ""


def _source_from_url(url: str) -> str:
    host = urlparse(url or "").netloc.strip()
    return host or ""


def _source_for_job(job: dict, publish_status: dict) -> str:
    source_name = str(publish_status.get("source_name") or "").strip()
    if source_name:
        return source_name

    description_source = _source_from_description(str(job.get("description") or ""))
    if description_source:
        return description_source

    source_url = str(publish_status.get("source_url") or "").strip()
    return _source_from_url(source_url) or "unknown"


def _youtube_video_id(job: dict, publish_status: dict) -> str:
    upload_video_id = str(job.get("upload_video_id") or "").strip()
    if upload_video_id:
        return upload_video_id

    platforms = publish_status.get("platforms")
    if isinstance(platforms, dict):
        youtube = platforms.get("youtube")
        if isinstance(youtube, dict):
            return str(youtube.get("remote_id") or "").strip()
    return ""


def _material_terms(job: dict) -> tuple[str, ...]:
    raw_terms = job.get("material_terms")
    if not isinstance(raw_terms, list):
        return ()
    return tuple(str(term).strip() for term in raw_terms if str(term).strip())


def build_daily_job_report(
    root_dir: str,
    report_date: date | None = None,
    timezone_name: str = "Asia/Taipei",
) -> DailyJobReport:
    root = Path(root_dir)
    tz = _timezone_for_name(timezone_name)
    target_date = report_date or datetime.now(tz).date()
    jobs_dir = root / "storage" / "auto_publish" / "jobs"
    status_dir = root / "storage" / "auto_publish" / "publish_status"

    entries: list[DailyJobEntry] = []
    source_counts: Counter[str] = Counter()
    material_term_counts: Counter[str] = Counter()

    for job_file in sorted(jobs_dir.glob("*.json")):
        job = _load_json_file(job_file)
        timestamp = _parse_timestamp(str(job.get("timestamp") or ""))
        if timestamp is None or timestamp.astimezone(tz).date() != target_date:
            continue

        task_id = str(job.get("task_id") or job_file.stem).strip()
        publish_status = _load_json_file(status_dir / f"{task_id}.json")
        source = _source_for_job(job, publish_status)
        terms = _material_terms(job)
        title = str(job.get("title") or "").strip()

        source_counts[source] += 1
        material_term_counts.update(terms)
        entries.append(
            DailyJobEntry(
                task_id=task_id,
                timestamp=timestamp,
                title=title,
                success=bool(job.get("success")),
                privacy_status=str(job.get("privacy_status") or "").strip(),
                upload_video_id=_youtube_video_id(job, publish_status),
                failure_stage=str(job.get("failure_stage") or "").strip(),
                error=str(job.get("error") or "").strip(),
                source=source,
                material_terms=terms,
                title_has_error=_title_has_error(title),
                job_file=str(job_file),
            )
        )

    entries.sort(key=lambda entry: entry.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return DailyJobReport(
        report_date=target_date,
        timezone_name=timezone_name,
        entries=tuple(entries),
        source_counts=source_counts,
        material_term_counts=material_term_counts,
    )


def _shorten(text: str, max_length: int = 90) -> str:
    value = " ".join((text or "").split())
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _format_count_section(title: str, counts: Counter[str], limit: int = 8) -> list[str]:
    lines = [title]
    if not counts:
        return lines + ["- none"]
    for value, count in counts.most_common(limit):
        lines.append(f"- {value}: {count}")
    return lines


def render_daily_job_report(report: DailyJobReport) -> str:
    lines = [
        f"VideoTurn Daily Report - {report.report_date.isoformat()} ({report.timezone_name})",
        "",
        "Summary",
        f"- Jobs: {report.total_jobs}",
        f"- Success: {report.success_count}",
        f"- Failure: {report.failure_count}",
        f"- Public uploads: {report.public_upload_count}",
        f"- Error-like titles: {report.error_title_count}",
    ]

    public_entries = [
        entry
        for entry in report.entries
        if entry.success and entry.privacy_status == "public" and entry.upload_video_id
    ]
    lines += ["", "Public videos"]
    if public_entries:
        for entry in public_entries:
            lines.append(
                f"- {entry.upload_video_id} | {entry.task_id} | {_shorten(entry.title)}"
            )
    else:
        lines.append("- none")

    failed_entries = [entry for entry in report.entries if not entry.success]
    lines += ["", "Failures"]
    if failed_entries:
        for entry in failed_entries:
            stage = entry.failure_stage or "unknown"
            error = _shorten(entry.error or "unknown error", 120)
            lines.append(
                f"- {entry.task_id} | stage={stage} | {error} | {_shorten(entry.title)}"
            )
    else:
        lines.append("- none")

    error_title_entries = [entry for entry in report.entries if entry.title_has_error]
    lines += ["", "Error-like titles"]
    if error_title_entries:
        for entry in error_title_entries:
            lines.append(f"- {entry.task_id} | {_shorten(entry.title, 120)}")
    else:
        lines.append("- none")

    lines += [""] + _format_count_section("Sources", report.source_counts)
    lines += [""] + _format_count_section("Material terms", report.material_term_counts)
    return "\n".join(lines).rstrip() + "\n"


def default_report_path(root_dir: str, report_date: date) -> Path:
    report_dir = Path(root_dir) / "storage" / "auto_publish" / "reports"
    return report_dir / f"daily_{report_date.isoformat()}.txt"
