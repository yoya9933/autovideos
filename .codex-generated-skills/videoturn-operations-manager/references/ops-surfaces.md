# VideoTurn Operations Surfaces

## Artifact Priority

1. `storage/auto_publish/jobs/<task_id>.json`
   - Source of truth for a run.
   - Useful fields: `task_id`, `created_at`, `status`, `failure_stage`, `error`, `job_path`, `privacy_status`, `source`, `source_url`, `title`, `video_path`, `audio_path`, `subtitle_path`, `duration`, `quality_issues`, `upload_result`, `video_id`, `publish_results`, `platform_results`, `publish_state_path`.
2. `storage/auto_publish/pending_upload.json`
   - First recovery surface when a video was generated but upload or OAuth failed.
   - If this exists, inspect it before regenerating video.
3. `storage/auto_publish/logs/daily.log` and `storage/auto_publish/logs/daily_YYYY-MM-DD.log`
   - Timeline sources when job JSON is missing or incomplete.
   - Search for: `job metadata saved`, `failure`, `failure_stage`, `quality_gate`, `upload`, `video_id`, `notify`, `429`, `quota`, `oauth2.googleapis.com/token`, `youtubeSignupRequired`, `source_context`.
4. `storage/auto_publish/publish_status/<task_id>.json`
   - Per-platform publish state.
   - Keep separate from RSS `seen.json`.
5. `storage/auto_publish/seen.json`
   - RSS entry dedupe only. Do not treat it as publish success.
6. Outer `task_morning.xml`, `task_afternoon.xml`, and `install_scheduler.bat`
   - Scheduler source files. Use only when scheduling is relevant.

## Stage Interpretation

- `no_rss_feeds`: config or feed configuration problem.
- `source_selection`: RSS fetch, article text, LLM selection, or source guard problem.
- `video_generation`: script, TTS, material, subtitle, or FFmpeg problem.
- `quality_gate`: video exists but failed configured quality checks.
- `upload` or `youtube_publish`: YouTube or platform upload failure.
- `notification`: publish may have succeeded; notification failed separately.

When `daily_quality_gate_enabled = false`, do not present a missing quality-gate block as a failure.

## Focused Inspection Patterns

Use narrow searches before broad scanning:

- `job metadata saved|failure_stage|quality_gate|video_id|notify|upload|429|quota|source_context`
- `pending_upload`
- `oauth2.googleapis.com/token`
- `storage/auto_publish/jobs`
- `storage/auto_publish/publish_status`
- `daily_quality_gate_enabled`
- `youtube_upload_privacy_status`
- `daily_publish_platforms`

## Commands To Prefer

From the app repo:

- Use `..\lib\python\python.exe daily_job_report.py --date YYYY-MM-DD` for daily summaries.
- Use `..\lib\python\python.exe daily_job_report.py --send-email` only when the user asks to send the report.
- Use targeted `py_compile` only for touched Python files.
- Use targeted `unittest` only when code changed or behavior is unclear.

From the outer workspace:

- Use `run_daily_auto_publish.bat` for realistic manual runs.
- Use `install_scheduler.bat --xml-only` only when checking scheduler XML path consistency.
- Avoid mutating Windows Task Scheduler during ordinary daily-run triage.

## Reporting Checklist

Include the concrete date checked, then:

- Did it run?
- Latest task id.
- Job JSON path.
- Stage and error if failed.
- Video artifact path if created.
- Uploaded video id and privacy if uploaded.
- Publish status path if multi-platform publish ran.
- Pending upload path if upload failed after video generation.
- Notification status if visible.
- One next safe action.
