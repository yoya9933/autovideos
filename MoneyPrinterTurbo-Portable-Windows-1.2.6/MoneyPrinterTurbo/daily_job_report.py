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
        "--save",
        action="store_true",
        help="Save the report under storage/auto_publish/reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root_dir = str(Path(__file__).resolve().parent)
    report = build_daily_job_report(
        root_dir=root_dir,
        report_date=_parse_report_date(args.date),
        timezone_name=args.timezone,
    )
    body = render_daily_job_report(report)

    if args.save:
        output_path = default_report_path(root_dir, report.report_date)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
        print(f"report saved: {output_path}")

    print(body)

    if args.send_email:
        from app.services.notification import EmailNotifier

        subject = f"VideoTurn Daily Report - {report.report_date.isoformat()}"
        sent = EmailNotifier().send(subject, body)
        if not sent:
            print("email report was not sent; email notifier is not configured or failed")
            return 1
        print("email report sent")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
