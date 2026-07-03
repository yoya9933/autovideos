import unittest

from app.services.topic_profiles import load_topic_profile


class TestTopicProfiles(unittest.TestCase):
    def test_loads_named_profile_from_nested_config(self):
        profile = load_topic_profile(
            {
                "daily_default_topic_profile": "tech",
                "daily_topic_profiles": {
                    "consumer_money": {
                        "feeds": ["https://example.com/consumer.xml"],
                        "candidate_count": 24,
                        "focus_keywords": ["漲價", "訂閱"],
                        "focus_keyword_bonus": 4,
                        "excluded_keywords": ["信用卡推薦"],
                        "editorial_brief": "先說明一般人會多付多少錢。",
                    }
                },
            },
            "consumer_money",
        )

        self.assertEqual(profile.name, "consumer_money")
        self.assertEqual(profile.feed_urls, ("https://example.com/consumer.xml",))
        self.assertEqual(profile.candidate_count, 24)
        self.assertEqual(profile.focus_keywords, ("漲價", "訂閱"))
        self.assertEqual(profile.focus_bonus, 4)
        self.assertEqual(profile.excluded_keywords, ("信用卡推薦",))
        self.assertEqual(profile.editorial_brief, "先說明一般人會多付多少錢。")

    def test_legacy_flat_config_is_used_for_tech_profile(self):
        profile = load_topic_profile(
            {
                "daily_rss_feeds": ["https://example.com/tech.xml"],
                "daily_candidate_count": 12,
                "daily_focus_keywords": ["AI", "晶片"],
                "daily_focus_keyword_bonus": 8,
            },
            "tech",
        )

        self.assertEqual(profile.name, "tech")
        self.assertEqual(profile.feed_urls, ("https://example.com/tech.xml",))
        self.assertEqual(profile.candidate_count, 12)
        self.assertEqual(profile.focus_keywords, ("AI", "晶片"))
        self.assertEqual(profile.focus_bonus, 8)
        self.assertEqual(profile.excluded_keywords, ())

    def test_legacy_single_feed_string_is_preserved(self):
        profile = load_topic_profile(
            {"daily_rss_feeds": "https://example.com/tech.xml"},
            "tech",
        )

        self.assertEqual(profile.feed_urls, ("https://example.com/tech.xml",))

    def test_non_tech_profile_does_not_inherit_legacy_tech_fields(self):
        profile = load_topic_profile(
            {
                "daily_rss_feeds": ["https://example.com/tech.xml"],
                "daily_focus_keywords": ["AI", "晶片"],
                "daily_topic_profiles": {"consumer_money": {}},
            },
            "consumer_money",
        )

        self.assertEqual(profile.feed_urls, ())
        self.assertEqual(profile.focus_keywords, ())

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown topic profile: missing"):
            load_topic_profile(
                {"daily_topic_profiles": {"tech": {"feeds": []}}},
                "missing",
            )


if __name__ == "__main__":
    unittest.main()
