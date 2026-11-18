"""Run from backend: python -m unittest discover -s tests -p test_review_guard.py"""
import unittest
from unittest.mock import patch
from app.services.translation import translator as tr
from app.services.translation import chapter_pipeline as pipeline


class ReviewGuardTests(unittest.TestCase):
    def review(self, draft, revised, model="qwen3:4b"):
        with patch.object(tr, "translate_segment", return_value={
            "translation": draft, "model": model, "provider": "ollama", "warnings": [],
        }), patch.object(tr, "generate", return_value=revised), \
             patch.object(tr, "check_consistency", return_value=[]):
            return tr.translate_and_review("Un pasaje del original.", model=model)

    def assert_preserved(self, draft, revised):
        result = self.review(draft, revised)
        self.assertEqual(result["translation"], draft)
        self.assertEqual(result["warnings"][-1]["type"], "editorial_review_pending")
        return result

    def test_recorded_truncated_action(self):
        self.assert_preserved(
            "One of them drove the pickup truck up to the delivery ramp, opened the door, and immediately went inside the offices.",
            "One of them drove the pickup truck up to the delivery ramp, opened the:")

    def test_recorded_duplicated_clause(self):
        self.assert_preserved(
            "The Gadian group needed people like this to manipulate them at will and govern the countries underwater.",
            "The Gadian group needed people like this to manipulate them at will and govern the: "
            "The Gadian group needed people like this to manipulate them at will and govern the countries underwater.")

    def test_recorded_broken_name(self):
        self.assert_preserved(
            "The secret band of the Gadianes had fulfilled their mission: millions were killed.",
            "The secret band of the G: Gadianes had completed their mission: millions were killed.")

    def test_recorded_word_repetition(self):
        self.assert_preserved(
            "That night, biochemical substances were poured into those bombs, and it was only a matter of minutes.",
            "That night, biochemical substances were poured into those bombs, and it, it was only a matter of minutes.")

    def test_large_shortening(self):
        self.assert_preserved(
            "She opened the door, walked down the hallway, took her coat, and left without saying a word.",
            "She opened the door and left.")

    def test_legitimate_improvement_both_models(self):
        for model in ("qwen3:4b", "qwen2.5:3b"):
            result = self.review(
                "She did not take a bad decision and remained at home.",
                "She avoided making a bad decision and stayed home.", model)
            self.assertEqual(result["translation"],
                             "She avoided making a bad decision and stayed home.")
            self.assertEqual(result["warnings"], [])

    def test_existing_literary_repetition_allowed(self):
        self.assertEqual(tr.review_damage_reasons(
            "Never, never would she leave him.",
            "Never, never would she abandon him."), [])

    def test_separator_direct_never_calls_ollama(self):
        for source in (". . . . .", "  ***  ", "— — —", "…"):
            with patch.object(tr, "generate") as generate:
                result = tr.translate_and_review(source, model="qwen3:4b")
                self.assertEqual(result["translation"], source)
                generate.assert_not_called()

    def test_separator_pipeline_preserves_exact_layout(self):
        source = " \t. . . . .\r\n\n***\n"
        with patch.object(pipeline, "translate_and_review") as generate:
            result = pipeline.translate_chapter(source, {}, "qwen3:4b")
            self.assertEqual(result["translation"], source)
            generate.assert_not_called()

    def test_mixed_prose_separator_keeps_order(self):
        with patch.object(pipeline, "translate_and_review", side_effect=[
            {"translation": "First.", "warnings": []},
            {"translation": "Last.", "warnings": []},
        ]) as generate:
            result = pipeline.translate_chapter("Primero.\n\n. . . . .\nUltimo.\n", {}, "qwen3:4b")
            self.assertEqual(result["translation"], "First.\n\n. . . . .\nLast.\n")
            self.assertEqual(result["segments"], 2)
            self.assertEqual(generate.call_count, 2)

    def test_surface_checks_do_not_claim_semantic_fidelity(self):
        # Semantic mistranslations in the draft still need bilingual evaluation.
        self.assertEqual(tr.review_damage_reasons(
            "Millions died when the pumps stopped.",
            "Millions died when the pumps stopped."), [])


if __name__ == "__main__":
    unittest.main()

