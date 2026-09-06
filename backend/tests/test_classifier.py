import unittest
from unittest.mock import patch

from app.classifier import classify_email
from app.config import settings
from app.llm_router import LlmUnavailable, llm_configured


class LlmConfiguredTests(unittest.TestCase):
    def test_either_key_is_enough(self):
        with patch.object(settings, "openai_api_key", ""), patch.object(settings, "anthropic_api_key", "sk-ant"):
            self.assertTrue(llm_configured())
        with patch.object(settings, "openai_api_key", "sk-openai"), patch.object(settings, "anthropic_api_key", ""):
            self.assertTrue(llm_configured())
        with patch.object(settings, "openai_api_key", ""), patch.object(settings, "anthropic_api_key", ""):
            self.assertFalse(llm_configured())


class ClassifierLlmTests(unittest.TestCase):
    def test_no_key_uses_heuristic(self):
        with patch("app.classifier.llm_configured", return_value=False):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertFalse(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")
        self.assertEqual(out.action_type, "archive")

    def test_llm_is_primary_when_configured(self):
        raw = {
            "autonomy_level": "ask_first",
            "confidence": 0.81,
            "action_type": "draft_reply",
            "reasoning": "This is a person, not a newsletter.",
            "draft": "Thanks, I'll take a look.",
            "label": None,
        }
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", return_value=raw
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
            )
        self.assertTrue(out.used_llm)
        self.assertEqual(out.autonomy_level, "ask_first")
        self.assertEqual(out.action_type, "draft_reply")
        self.assertEqual(out.reasoning, "This is a person, not a newsletter.")

    def test_llm_failure_falls_back_to_heuristic(self):
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", side_effect=LlmUnavailable("down")
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertFalse(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")

    def test_invalid_llm_level_falls_back_to_heuristic_level(self):
        raw = {
            "autonomy_level": "yolo",
            "confidence": 0.9,
            "action_type": "teleport",
            "reasoning": "n/a",
            "draft": None,
            "label": None,
        }
        with patch("app.classifier.llm_configured", return_value=True), patch(
            "app.classifier.complete_decision", return_value=raw
        ):
            out = classify_email(
                "Morning Brew <crew@morningbrew.com>",
                "☕ markets",
                "Good morning. Unsubscribe at the bottom.\n",
                labels=["CATEGORY_PROMOTIONS"],
                list_unsubscribe="<mailto:unsub@morningbrew.com>",
            )
        self.assertTrue(out.used_llm)
        self.assertEqual(out.autonomy_level, "proceed_silently")
        self.assertEqual(out.action_type, "archive")


if __name__ == "__main__":
    unittest.main()
