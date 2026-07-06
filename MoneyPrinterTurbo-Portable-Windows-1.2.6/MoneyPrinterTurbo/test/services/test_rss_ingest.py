import unittest
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services.rss_ingest import (
    FeedEntry,
    build_script_prompt,
    build_title_prompt,
    collect_candidate_entries,
    generate_video_title,
    has_enough_source_context,
    is_low_information_feed_entry,
    is_same_event_entry,
    load_seen_entries,
    save_seen_entries,
    select_best_entry_for_video,
)


def _entry(title: str = "維基百科2026年5月30日典範條目") -> FeedEntry:
    return FeedEntry(
        feed_url="Tech News",
        entry_id="entry-1",
        title=title,
        summary="新一代 AI 晶片需求快速升溫，供應鏈成本上升，可能影響雲端服務與消費電子價格。",
        link="https://example.com/ai-chip",
        published="2026-06-04",
    )


class TestRssIngestTitleGeneration(unittest.TestCase):
    def test_build_title_prompt_requires_truthful_clickbait(self):
        prompt = build_title_prompt(_entry())

        self.assertIn("高點擊率但真實", prompt)
        self.assertIn("影片長標題", prompt)
        self.assertIn("縮圖短標題", prompt)
        self.assertIn("原始標題：維基百科2026年5月30日典範條目", prompt)

    def test_generate_video_title_uses_cleaned_ai_title(self):
        with patch(
            "app.services.llm._generate_response",
            return_value='<long>標題：「AI 晶片突然變貴的真正原因」 #AI</long>\n<short>AI晶片突變貴</short>',
        ):
            title, short_title = generate_video_title(_entry())

        self.assertEqual(title, "AI 晶片突然變貴的真正原因")
        self.assertEqual(short_title, "AI晶片突變貴")

    def test_generate_video_title_falls_back_to_rss_title_on_llm_failure(self):
        with patch("app.services.llm._generate_response", side_effect=RuntimeError("offline")):
            title, short_title = generate_video_title(_entry(), title_prefix="Shorts")

        self.assertEqual(title, "Shorts 維基百科2026年5月30日典範條目")
        self.assertEqual(short_title, "Shorts維基")

    def test_build_script_prompt_does_not_force_padding_short_sources(self):
        prompt = build_script_prompt(_entry(), max_summary_length=20)

        self.assertIn("寧可縮短到 35-50 秒", prompt)
        self.assertIn("不要湊字數", prompt)
        self.assertIn("補不存在的細節", prompt)

    def test_build_script_prompt_requires_short_hook_formulas(self):
        prompt = build_script_prompt(_entry())

        for formula in ("結果先講", "數字衝擊", "衝突對立", "風險提醒", "反常識"):
            self.assertIn(formula, prompt)

        self.assertIn("前 3 秒", prompt)
        self.assertIn("18 個中文字以內", prompt)
        self.assertIn("禁止使用「今天我們來聊」", prompt)

    def test_editorial_brief_is_added_to_title_and_script_prompts(self):
        brief = "先說明一般人會多付、少拿或承擔什麼風險。"

        self.assertIn(brief, build_title_prompt(_entry(), editorial_brief=brief))
        self.assertIn(brief, build_script_prompt(_entry(), editorial_brief=brief))


    def test_build_script_prompt_fits_video_params_limit_with_long_context(self):
        entry = FeedEntry(
            feed_url="https://example.com/feed",
            entry_id="long-entry",
            title="Long article title",
            summary="summary " * 120,
            link="https://example.com/article",
            published="2026-07-06",
        )

        prompt = build_script_prompt(
            entry,
            full_text="full article context " * 160,
            editorial_brief="editorial brief " * 40,
        )

        self.assertLessEqual(len(prompt), 2000)
        VideoParams(video_subject="subject", video_script_prompt=prompt)


class TestSeenEntryState(unittest.TestCase):
    def test_seen_state_saves_timestamped_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = str(Path(tmp_dir) / "seen.json")

            save_seen_entries(state_file, {"entry-1"})

            payload = json.loads(Path(state_file).read_text(encoding="utf-8"))
            self.assertEqual(payload["retention_days"], 90)
            self.assertEqual(payload["seen_entries"][0]["entry_id"], "entry-1")
            self.assertIn("seen_at", payload["seen_entries"][0])
            self.assertEqual(load_seen_entries(state_file), {"entry-1"})

    def test_seen_state_prunes_records_older_than_retention(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "seen.json"
            old_seen_at = (
                datetime.now(timezone.utc) - timedelta(days=91)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            state_file.write_text(
                json.dumps(
                    {
                        "seen_entries": [
                            {"entry_id": "old-entry", "seen_at": old_seen_at},
                            {"entry_id": "legacy-entry"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_seen_entries(str(state_file)), {"legacy-entry"})

            save_seen_entries(str(state_file), {"old-entry", "legacy-entry", "new-entry"})
            payload = json.loads(state_file.read_text(encoding="utf-8"))
            saved_ids = {item["entry_id"] for item in payload["seen_entries"]}

            self.assertNotIn("old-entry", saved_ids)
            self.assertIn("legacy-entry", saved_ids)
            self.assertIn("new-entry", saved_ids)


class TestLowInformationFiltering(unittest.TestCase):
    def test_google_trends_keyword_entry_is_low_information(self):
        entry = FeedEntry(
            feed_url="Google Trends",
            entry_id="trend-1",
            title="AI 手機",
            summary="",
            link="https://trends.google.com/trending/rss?geo=TW",
            published="",
        )

        self.assertTrue(is_low_information_feed_entry(entry))

    def test_article_with_substantial_summary_is_not_low_information(self):
        entry = FeedEntry(
            feed_url="Tech News",
            entry_id="article-1",
            title="AI 晶片需求升溫，供應鏈開始調整產能",
            summary="新一代 AI 晶片需求快速升溫，供應鏈成本上升，雲端服務商與消費電子品牌都開始調整採購策略，市場也重新評估資料中心投資節奏。",
            link="https://example.com/ai-chip",
            published="2026-06-04",
        )

        self.assertFalse(is_low_information_feed_entry(entry))

    def test_source_context_allows_full_text_fallback(self):
        entry = FeedEntry(
            feed_url="Tech News",
            entry_id="article-2",
            title="AI 晶片需求升溫",
            summary="短摘要",
            link="https://example.com/ai-chip",
            published="2026-06-04",
        )

        self.assertTrue(has_enough_source_context(entry, full_text="x" * 300))
        self.assertFalse(has_enough_source_context(entry, full_text="x" * 100))


class TestFocusAndEventDeduping(unittest.TestCase):
    @staticmethod
    def _candidate(feed: str, entry_id: str, title: str) -> FeedEntry:
        return FeedEntry(
            feed_url=feed,
            entry_id=entry_id,
            title=title,
            summary=f"{title}，這項變化涉及明確費用與一般消費者權益，來源提供完整事件背景與具體影響。",
            link=f"https://example.com/{entry_id}",
            published="2026-07-03",
        )

    def test_same_event_entries_are_detected(self):
        left = FeedEntry(
            feed_url="A",
            entry_id="1",
            title="NVIDIA 發表新 AI 晶片，資料中心效能大提升",
            summary="NVIDIA 發表新 AI 晶片，鎖定資料中心市場，雲端服務商也開始評估新一代算力需求。",
            link="https://example.com/a",
        )
        right = FeedEntry(
            feed_url="B",
            entry_id="2",
            title="輝達發表新 AI 晶片，資料中心效能大提升",
            summary="輝達發表新 AI 晶片，鎖定資料中心市場，雲端服務商也開始評估新一代算力需求。",
            link="https://example.com/b",
        )

        self.assertTrue(is_same_event_entry(left, right))

    def test_collect_candidate_entries_skips_duplicate_events(self):
        entries = [
            FeedEntry(
                feed_url="A",
                entry_id="1",
                title="台積電 AI 晶片訂單升溫，供應鏈開始調整產能",
                summary="台積電 AI 晶片需求快速升溫，供應鏈成本上升，雲端服務商與消費電子品牌都開始調整採購策略。",
                link="https://example.com/a",
            ),
            FeedEntry(
                feed_url="B",
                entry_id="2",
                title="台積電 AI 晶片訂單升溫，供應鏈開始調整產能",
                summary="另一來源報導同一事件，台積電 AI 晶片需求升溫，供應鏈開始調整產能與採購策略。",
                link="https://example.com/b",
            ),
        ]

        with patch("app.services.rss_ingest.fetch_feed_entries", return_value=entries):
            candidates = collect_candidate_entries(["https://example.com/feed"], set(), limit=5)

        self.assertEqual([candidate.entry_id for candidate in candidates], ["1"])

    def test_collect_candidate_entries_round_robins_across_feeds(self):
        feed_a = [
            self._candidate("A", "a1", "訂閱平台調漲月費引發退訂潮"),
            self._candidate("A", "a2", "超商咖啡漲價反映原料成本"),
        ]
        feed_b = [
            self._candidate("B", "b1", "網購退款流程新增手續費"),
            self._candidate("B", "b2", "會員制度改版影響點數權益"),
        ]

        with patch(
            "app.services.rss_ingest.fetch_feed_entries",
            side_effect=[feed_a, feed_b],
        ):
            candidates = collect_candidate_entries(["A", "B"], set(), limit=4)

        self.assertEqual(
            [candidate.entry_id for candidate in candidates],
            ["a1", "b1", "a2", "b2"],
        )

    def test_collect_candidate_entries_filters_profile_exclusions(self):
        entries = [
            self._candidate("A", "promo", "信用卡推薦限時申辦送好禮"),
            self._candidate("A", "news", "信用卡海外手續費調整引發爭議"),
        ]

        with patch("app.services.rss_ingest.fetch_feed_entries", return_value=entries):
            candidates = collect_candidate_entries(
                ["A"],
                set(),
                limit=5,
                excluded_keywords=["信用卡推薦", "申辦送好禮"],
            )

        self.assertEqual([candidate.entry_id for candidate in candidates], ["news"])

    def test_selection_prompt_contains_profile_editorial_brief(self):
        brief = "選擇有具體金額與一般人損益的消費題。"
        candidate = self._candidate("A", "consumer", "串流平台調漲訂閱費")

        with patch("app.services.llm._generate_response", return_value="1") as generate:
            selected = select_best_entry_for_video(
                [candidate],
                focus_keywords=["漲價", "訂閱"],
                editorial_brief=brief,
            )

        self.assertEqual(selected, candidate)
        self.assertIn(brief, generate.call_args.args[0])

    def test_focus_keywords_bias_fallback_selection(self):
        broad = FeedEntry(
            feed_url="Science",
            entry_id="broad",
            title="大型研究揭露睡眠與健康的新關聯",
            summary="研究團隊追蹤大量受試者，分析睡眠品質、生活型態與健康風險之間的關聯，結果顯示規律睡眠仍是重要因素。",
            link="https://example.com/health",
        )
        focused = FeedEntry(
            feed_url="Tech",
            entry_id="focused",
            title="NVIDIA AI 晶片需求再升溫",
            summary="供應鏈指出 NVIDIA AI 晶片需求升溫，資料中心採購節奏加快，相關雲端服務商也開始調整投資計畫。",
            link="https://example.com/nvidia-ai",
        )

        with patch("app.services.llm._generate_response", return_value="invalid"):
            selected = select_best_entry_for_video(
                [broad, focused],
                focus_keywords=["NVIDIA", "AI", "晶片"],
                focus_bonus=8,
            )

        self.assertEqual(selected, focused)


if __name__ == "__main__":
    unittest.main()
