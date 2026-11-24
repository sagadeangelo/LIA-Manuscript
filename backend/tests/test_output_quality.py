import io
import json
import os
import unittest
from unittest.mock import patch

from app.services.translation import translator as tr
from app.services.translation.consistency_checker import fidelity_warnings
from app.services.translation.output_quality import output_issues, paragraph_output_warnings
from app.services.providers import ollama_provider as provider


class OutputQualityTests(unittest.TestCase):
    source = "Ella abrio la puerta y entro en la oficina."

    def test_bad_output_families(self):
        cases = [
            (None, "invalid_translation_type"),
            (" ", "empty_translation"),
            (self.source, "copied_source"),
            ("She opened the door.\nShe entered the office.", "paragraph_structure_changed"),
            ("She wanted to: pass the test.", "broken_function_word_colon"),
            ("She harmed the: human mind.", "broken_function_word_colon"),
            ("She used our: freedom.", "broken_function_word_colon"),
            ("Here is the translation: She left.", "model_instruction_leakage"),
            ("The text provided is a series of periods with no content.", "model_instruction_leakage"),
            ("Translate the following text into English: She left.", "model_instruction_leakage"),
            ("```text\nShe left.\n```", "unexpected_code_fence"),
            ('{"translation":"She left."}', "unexpected_translation_wrapper"),
            ("The V: Velorians arrived.", "broken_name_fragment"),
            ("She opened the:", "unfinished_colon_fragment"),
        ]
        for target, code in cases:
            with self.subTest(target=target):
                self.assertIn(code, output_issues(self.source, target))

    def test_literal_symbol_is_not_a_broken_name(self):
        self.assertNotIn("broken_name_fragment", output_issues(
            "En el anillo estaba la letra V.", "The ring bore V: Velorian."))

    def test_legitimate_colon_is_preserved(self):
        self.assertEqual(output_issues(
            self.source, "She had a choice: open the door or leave."), [])

    def test_good_translation(self):
        self.assertEqual(output_issues(
            self.source, "She opened the door and entered the office."), [])

    def test_novel_can_discuss_text_and_translation(self):
        self.assertEqual(output_issues(
            "El texto proporcionado describe una puerta.",
            "The text provided is a description of a door."), [])
        self.assertEqual(output_issues(
            "Aqui esta la traduccion: ella salio.",
            "Here is the translation: she left."), [])

    def test_paragraph_annotations_do_not_guess_alignment(self):
        self.assertEqual(paragraph_output_warnings("Uno.\nDos.", "One and two."), [])
        warnings = paragraph_output_warnings(
            "Titulo\n\n" + self.source, "Title\n\nShe opened the:")
        self.assertTrue(warnings)
        self.assertEqual({w["source_paragraph"] for w in warnings}, {2})

    def test_initial_bad_outputs_are_retried_and_never_returned(self):
        for bad in ("She wanted to: pass.", "Here is the translation: She entered."):
            with self.subTest(bad=bad), patch.object(tr, "generate", return_value=bad) as generate:
                with self.assertRaises(ValueError):
                    tr.translate_segment(self.source, model="qwen2.5:3b")
                self.assertEqual(generate.call_count, 2)

    def test_initial_retry_can_recover(self):
        good = "She opened the door and entered the office."
        with patch.object(tr, "generate", side_effect=["She opened the:", good]):
            self.assertEqual(tr.translate_segment(self.source, model="qwen3:4b")["translation"], good)

    def test_new_polysemy_warnings_are_context_scoped(self):
        cases = [
            ("Sus pantalones tenian bolsas.", "His pants had bags.", "clothing_polysemy"),
            ("La luz tintineante se apago.", "The chime-like light went out.", "visual_polysemy"),
        ]
        for source, target, code in cases:
            self.assertIn(code, {w["code"] for w in fidelity_warnings(source, target)})
        self.assertEqual(fidelity_warnings("Las bolsas pesaban.", "The bags were heavy."), [])
        self.assertEqual(fidelity_warnings("Un sonido tintineante.", "A tinkling sound."), [])

    def test_explicit_prevention_resolves_only_the_scope_warning(self):
        source = "Una fuerza hizo que no tomara una mala decision y me uniera al grupo."
        valid = "A force prevented me from making a bad decision and joining the group."
        bad = "A force prevented me from making a bad decision, but I joined the group."
        self.assertNotIn("negation_scope", {w["code"] for w in fidelity_warnings(source, valid)})
        self.assertIn("negation_scope", {w["code"] for w in fidelity_warnings(source, bad)})

    def test_large_compression_is_review_warning_not_proof_of_omission(self):
        source = "Ella abrio la puerta y camino por el pasillo, recogio su abrigo y sus llaves, miro al perro y salio hacia el bosque."
        target = "She left."
        warning = next(w for w in fidelity_warnings(source, target) if w["code"] == "possible_content_omission")
        self.assertEqual(warning["severity"], "review")


class SelectiveReviewTests(unittest.TestCase):
    source = "El consejo dirigia el pais por debajo del agua."
    original = "The council governed the country underwater, keeping its influence hidden."
    corrected = "The council governed the country behind the scenes, keeping its influence hidden."

    def draft(self, warnings):
        return {"translation": self.original, "model": "qwen3:4b",
                "provider": "ollama", "warnings": warnings}

    def test_no_warning_does_not_trigger_rewrite(self):
        with patch.dict(os.environ, {"LIA_EDITORIAL_REVIEW_POLICY": "selective"}), \
             patch.object(tr, "translate_segment", return_value=self.draft([])), \
             patch.object(tr, "generate") as generate:
            self.assertEqual(tr.translate_and_review(self.source)["translation"], self.original)
            generate.assert_not_called()

    def test_resolved_risk_can_return_candidate(self):
        warnings = fidelity_warnings(self.source, self.original)
        with patch.dict(os.environ, {"LIA_EDITORIAL_REVIEW_POLICY": "selective"}), \
             patch.object(tr, "translate_segment", return_value=self.draft(warnings)), \
             patch.object(tr, "generate", return_value=self.corrected) as generate:
            result = tr.translate_and_review(self.source)
            self.assertEqual(result["translation"], self.corrected)
            self.assertEqual(result["warnings"], [])
            self.assertEqual(generate.call_count, 1)

    def test_remaining_risk_keeps_original_and_notice(self):
        warnings = fidelity_warnings(self.source, self.original)
        with patch.dict(os.environ, {"LIA_EDITORIAL_REVIEW_POLICY": "selective"}), \
             patch.object(tr, "translate_segment", return_value=self.draft(warnings)), \
             patch.object(tr, "generate", return_value=self.original):
            result = tr.translate_and_review(self.source)
            self.assertEqual(result["translation"], self.original)
            self.assertEqual(result["warnings"][-1]["type"], "editorial_review_pending")

    def test_resolved_warning_cannot_override_new_corruption(self):
        warnings = fidelity_warnings(self.source, self.original)
        with patch.dict(os.environ, {"LIA_EDITORIAL_REVIEW_POLICY": "selective"}), \
             patch.object(tr, "translate_segment", return_value=self.draft(warnings)), \
             patch.object(tr, "generate", return_value=self.corrected.replace("the scenes", "the: scenes")):
            result = tr.translate_and_review(self.source)
            self.assertEqual(result["translation"], self.original)
            self.assertIn("broken_function_word_colon", result["warnings"][-1]["message"])

    def test_off_preserves_draft_even_with_warnings(self):
        with patch.dict(os.environ, {"LIA_EDITORIAL_REVIEW_POLICY": "off"}), \
             patch.object(tr, "translate_segment", return_value=self.draft([{"type": "fidelity_review", "code": "risk"}])), \
             patch.object(tr, "generate") as generate:
            tr.translate_and_review(self.source)
            generate.assert_not_called()

    def test_hymt_does_not_silently_switch_to_another_model(self):
        draft = self.draft([{"type": "fidelity_review", "code": "risk"}])
        draft["model"] = "lia-hymt2:1.8b-q8"
        with patch.object(tr, "translate_segment", return_value=draft), patch.object(tr, "generate") as generate:
            self.assertEqual(tr.translate_and_review(self.source), draft)
            generate.assert_not_called()


class ProviderCompletionTests(unittest.TestCase):
    def test_malformed_or_unfinished_response_is_not_accepted(self):
        for result in ([], None, {"done": False, "response": "She left."}):
            def respond(req, **kwargs):
                data = {"capabilities": []} if req.full_url.endswith("/api/show") else result
                return io.BytesIO(json.dumps(data).encode())
            with self.subTest(result=result), patch.object(provider.request, "urlopen", side_effect=respond):
                with self.assertRaises(provider.OllamaError):
                    provider.generate("Ella salio.", "qwen2.5:3b", "http://localhost", structured_translation=True)


if __name__ == "__main__":
    unittest.main()
