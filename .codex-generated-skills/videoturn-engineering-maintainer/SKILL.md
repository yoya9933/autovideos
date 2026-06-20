---
name: videoturn-engineering-maintainer
description: Maintain VideoTurn / MoneyPrinterTurbo pipeline code safely. Use when the user asks to modify or review Python services, auto_publish_youtube.py, config defaults, tests, platform publishers, RSS prompt implementation, scheduler scripts, Git state, repo hygiene, or cross-machine Codex/GitHub sync for this VideoTurn workspace.
---

# VideoTurn Engineering Maintainer

## Scope

Use this for code, tests, configuration, Git hygiene, and maintainability work in the VideoTurn / MoneyPrinterTurbo workspace.

Do not use this for pure content, visual, or operations questions unless the user asks for an implementation change.

## Project Context

- Outer workspace and current Git root: `D:\coding_202605051504_XY_Propose_Minutes\videoturn_202606011405_XY`
- App repo: `MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo`
- Portable Python: `MoneyPrinterTurbo-Portable-Windows-1.2.6\lib\python\python.exe`
- Core pipeline: `auto_publish_youtube.py`, `app\services\rss_ingest.py`, `app\services\llm.py`, `app\services\task.py`, `app\services\thumbnail.py`
- Publishing layer: `app\services\platform_publish.py`, `youtube_publisher.py`, `youtube_upload.py`, `instagram_reels_publish.py`, `facebook_reels_publish.py`
- Tests: `test\`, especially `test\services\`

## Workflow

1. Verify current repo state before edits with `git status --short` and protect unrelated user changes.
2. Inspect existing patterns before proposing or making changes.
3. Keep edits narrowly scoped to the requested behavior.
4. Prefer tests that directly cover changed behavior:
   - prompt/content logic: `test\services\test_rss_ingest.py`
   - publisher state and adapters: relevant `test\services\test_*publish*.py`
   - reports: `test\services\test_daily_job_report.py`
   - config or LLM routing: `test\services\test_llm.py` and targeted config checks
5. Use the portable Python interpreter for verification.
6. Never expose or commit secrets from `.env`, OAuth files, tokens, `config.toml`, or generated runtime artifacts.
7. For Git work, verify the actual root and remote before recommending push/clone commands.

## Change Safety

- Do not change public upload behavior unless explicitly requested.
- Keep `config.example.toml` and runtime config expectations aligned when adding public options.
- Do not regenerate videos as a substitute for fixing upload-only or metadata-only issues.
- Do not rewrite unrelated app files while skill or documentation work is in progress.
- When modifying scheduler scripts or XML, validate with `install_scheduler.bat --xml-only` before suggesting live Task Scheduler updates.

## Response Shape

Answer in Traditional Chinese by default:

- files inspected and why
- implementation summary
- verification commands and results
- remaining risk or required manual action
