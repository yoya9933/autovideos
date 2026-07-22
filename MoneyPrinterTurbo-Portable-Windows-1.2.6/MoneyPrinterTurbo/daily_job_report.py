from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from app.services.daily_job_report import (
    build_daily_job_report,
    default_report_path,
    render_daily_job_report,
)


def _parse_report_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _email_sent_marker_path(root_dir: str, report_date: date) -> Path:
    return default_report_path(root_dir, report_date).with_suffix(".email-sent")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a daily VideoTurn job report from auto_publish job JSON files."
    )
    parser.add_argument(
        "--date",
        default="",
        help="Report date in YYYY-MM-DD. Defaults to today in the selected timezone.",
    )
    parser.add_argument(
        "--timezone",
        default="Asia/Taipei",
        help="Timezone used to group UTC job timestamps. Defaults to Asia/Taipei.",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send the rendered report through the configured Email notifier.",
    )
    parser.add_argument(
        "--send-email-on-complete",
        action="store_true",
        help="Send only after the expected number of daily jobs is reached, once per date.",
    )
    parser.add_argument(
        "--expected-jobs",
        type=int,
        default=6,
        help="Expected jobs per day when using --send-email-on-complete (default: 6).",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the report under storage/auto_publish/reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.expected_jobs < 1:
        raise ValueError("--expected-jobs must be at least 1")

    root_dir = str(Path(__file__).resolve().parent)
    report = build_daily_job_report(
        root_dir=root_dir,
        report_date=_parse_report_date(args.date),
        timezone_name=args.timezone,
    )
    body = render_daily_job_report(report, expected_jobs=args.expected_jobs)

    if args.save:
        output_path = default_report_path(root_dir, report.report_date)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
        print(f"report saved: {output_path}")

    print(body)

    if args.send_email:
        marker_path = _email_sent_marker_path(root_dir, report.report_date)
        if args.send_email_on_complete:
            if report.total_jobs < args.expected_jobs:
                print(
                    f"email report deferred: {report.total_jobs}/{args.expected_jobs} jobs complete"
                )
                return 0
            if marker_path.exists():
                print("email report already sent for this date")
                return 0

        from app.services.notification import EmailNotifier

        subject = f"VideoTurn Daily Report - {report.report_date.isoformat()}"
        sent = EmailNotifier().send(subject, body)
        if not sent:
            print("email report was not sent; email notifier is not configured or failed")
            return 1
        if args.send_email_on_complete:
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text("sent\n", encoding="utf-8")
        print("email report sent")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
