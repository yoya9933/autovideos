---
name: videoturn-operations-manager
description: Operate and troubleshoot VideoTurn / MoneyPrinterTurbo daily auto-publish. Use when the user asks whether today's run happened, why a publish failed, where job JSON/log/upload evidence is, how scheduler tasks are configured, whether notifications worked, how to retry pending uploads, or how to safely rerun/backfill YouTube, Instagram Reels, or Facebook Reels publishing.
---

# VideoTurn Operations Manager

## Scope

Use this for operational checks around the daily RSS -> video -> publish workflow. Focus on current run state, concrete evidence, failure stage, and the next safe action.

Do not use this for content strategy, thumbnail style, or code implementation unless the user asks to convert the operational finding into a code/config change.

## Project Roots

- Outer workspace: `D:\coding_202605051504_XY_Propose_Minutes\videoturn_202606011405_XY`
- App repo: `MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo`
- Portable Python: `..\lib\python\python.exe` from the app repo
- Windows entrypoint: outer `run_daily_auto_publish.bat`
- Scheduler files: outer `task_morning.xml`, `task_afternoon.xml`, `install_scheduler.bat`

## Fast Workflow

1. Establish the concrete date and timezone from the thread context. Convert "today", "yesterday", and scheduler times to absolute dates.
2. Inspect artifacts before code:
   - `storage\auto_publish\jobs\*.json`
   - `storage\auto_publish\logs\daily.log` and dated daily logs
   - `storage\auto_publish\publish_status\*.json`
   - `storage\auto_publish\pending_upload.json`
   - scheduler XML only when scheduling is relevant
3. Report evidence first: task id, job path, stage/error, privacy, uploaded video id, output artifact path, publish status path, and notification result when visible.
4. Classify state:
   - did not run
   - running or partial output exists
   - failed before video
   - failed during quality gate
   - video created but upload skipped or failed
   - upload succeeded but thumbnail or notification failed
   - full success
5. Give one next safe action unless the user asks for options.

## Safety Rules

- Do not claim upload success from `final-1.mp4`; verify publish status or upload result.
- Treat `pending_upload.json` as the first recovery surface after upload/OAuth failures.
- Prefer private or unlisted reruns unless the user explicitly asks for public publishing.
- Do not expose secrets from `config.toml`, `.env`, OAuth files, tokens, or environment variables.
- Do not mutate Task Scheduler, public publishing, credentials, or config without explicit confirmation.

## When More Detail Is Needed

Read `references/ops-surfaces.md` for artifact fields, stage interpretation, focused search patterns, commands, and reporting checklist.

## Response Shape

Answer operationally in Traditional Chinese by default:

- current state in one sentence
- evidence list with paths, ids, stage, and error
- likely cause
- one next safe action
