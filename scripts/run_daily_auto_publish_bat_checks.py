import unittest
from pathlib import Path


class TestRunDailyAutoPublishBat(unittest.TestCase):
    def test_sends_daily_email_report_after_publish_and_preserves_publish_exit_code(self):
        outer_root = Path(__file__).resolve().parents[1]
        batch_lines = (
            outer_root / "run_daily_auto_publish.bat"
        ).read_text(encoding="utf-8").splitlines()

        joined = "\n".join(batch_lines)
        publish_command = (
            '"%CURRENT_DIR%lib\\python\\python.exe" auto_publish_youtube.py %* '
            '>> "%BAT_LOG%" 2>&1'
        )
        report_command = (
            '"%CURRENT_DIR%lib\\python\\python.exe" daily_job_report.py --send-email '
            '>> "%BAT_LOG%" 2>&1'
        )

        self.assertIn(publish_command, joined)
        self.assertIn('set "EXIT_CODE=%ERRORLEVEL%"', joined)
        self.assertIn(report_command, joined)
        self.assertIn('set "REPORT_EXIT_CODE=%ERRORLEVEL%"', joined)
        self.assertIn("endlocal & exit /b %EXIT_CODE%", joined)
        self.assertLess(batch_lines.index(publish_command), batch_lines.index(report_command))
        self.assertLess(
            batch_lines.index('set "EXIT_CODE=%ERRORLEVEL%"'),
            batch_lines.index(report_command),
        )
        self.assertLess(
            batch_lines.index(report_command),
            batch_lines.index("endlocal & exit /b %EXIT_CODE%"),
        )


if __name__ == "__main__":
    unittest.main()
