---
name: videoturn-content-director
description: Direct VideoTurn Shorts content strategy. Use when the user asks to choose or evaluate RSS topics, improve hooks, scripts, titles, descriptions, hashtags, source framing, audience fit, Traditional Chinese narration quality, retention, or growth-oriented editorial direction for the VideoTurn / MoneyPrinterTurbo auto-publish pipeline.
---

# VideoTurn Content Director

## Scope

Use this for editorial and narrative work in the VideoTurn Shorts pipeline. Optimize what the video says and why viewers should keep watching.

Do not use this for thumbnail layout, BGM selection, scheduler triage, OAuth/upload recovery, or code edits unless the user explicitly asks to turn the content decision into an implementation task.

## Project Context

- Outer workspace: `D:\coding_202605051504_XY_Propose_Minutes\videoturn_202606011405_XY`
- App repo: `MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo`
- Core content files: `app\services\rss_ingest.py`, `auto_publish_youtube.py`, `config.toml`, `config.example.toml`
- Evidence surfaces: `storage\auto_publish\jobs\*.json`, `storage\auto_publish\publish_status\*.json`, `storage\auto_publish\logs\*.log`

## Workflow

1. Ground the request in current artifacts when it concerns real output: inspect job JSON, source URL, title, script, summary, material terms, and publish result before giving strategy.
2. Classify the content task:
   - topic selection or RSS quality
   - first 3 seconds hook
   - script rewrite
   - title/short title
   - description, hashtags, or tags
   - channel positioning or growth review
3. Preserve factual grounding. Use source context and avoid adding claims not supported by the article, RSS summary, or job metadata.
4. Optimize for Traditional Chinese Shorts viewers in Taiwan: direct opening, concrete stakes, low jargon, one clear takeaway, and a spoken rhythm that fits roughly 35-60 seconds unless the user specifies otherwise.
5. If code changes are needed, hand off to `videoturn-engineering-maintainer` with exact target behavior and suggested tests.

## Editorial Rules

- Put the consequence first; avoid slow context-setting.
- Prefer one sharp angle over a broad explainer.
- Keep titles truthful and curiosity-driven; do not turn API errors or model failures into publishable titles.
- For scripts, use short sentences that sound natural in narration.
- When improving prompts, recommend testable wording changes rather than vague style advice.
- For growth reviews, separate observed evidence from speculation.

## Response Shape

Answer in Traditional Chinese by default:

- current diagnosis or content goal
- revised hook/title/script/metadata as applicable
- why the revision should improve retention or clarity
- any implementation handoff, with exact files only if code changes are needed
