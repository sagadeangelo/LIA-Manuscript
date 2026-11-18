import io
import json
import unittest
from unittest.mock import patch
from app.services.providers import ollama_provider as provider
from app.services.translation import translator as tr


class FidelityProfileTests(unittest.TestCase):
    def request(self, model):
        sent = []
        def respond(req, **kwargs):
            body = json.loads(req.data)
            if req.full_url.endswith("/api/show"):
                return io.BytesIO(b'{"capabilities":["thinking"]}')
            sent.append(body)
            text = "The pump stopped."
            result = text if body.get("raw") else json.dumps({"translation": text})
            return io.BytesIO(json.dumps({"response": result, "done_reason": "stop"}).encode())
        with patch.object(provider.request, "urlopen", side_effect=respond):
            result = provider.generate(
                "La bomba paro.", model, "http://127.0.0.1:11434",
                structured_translation=True, previous="Una tuberia.", following="Otra tuberia.",
                glossary={"Nombre": "Name"})
        self.assertEqual(result, "The pump stopped.")
        return sent[0]

    def test_hymt_native_prompt_excludes_adjacent_prose(self):
        for model in ("lia-hymt2:1.8b-q8", "hf.co/tencent/Hy-MT2-1.8B-GGUF:Q8_0"):
            body = self.request(model)
            self.assertTrue(body["raw"])
            self.assertNotIn("format", body)
            self.assertNotIn("system", body)
            self.assertIn("without any additional explanation:\nLa bomba paro.", body["prompt"])
            self.assertNotIn("Una tuberia.", body["prompt"])
            self.assertNotIn("Otra tuberia.", body["prompt"])
            self.assertNotIn("SOURCE TEXT:", body["prompt"])
            self.assertIn('"Nombre" translates to "Name"', body["prompt"])
            self.assertTrue(body["prompt"].endswith("<｜hy_Assistant｜>"))

    def test_qwen_retains_json_and_think_control(self):
        for model in ("qwen3:4b", "qwen2.5:3b"):
            body = self.request(model)
            self.assertFalse(body["think"])
            self.assertNotIn("raw", body)
            self.assertEqual(body["format"]["required"], ["translation"])
            self.assertEqual(json.loads(body["prompt"])["previous_context"], "Una tuberia.")

    def test_hymt_does_not_rewrite_draft(self):
        with patch.object(tr, "generate", return_value="She stayed home.") as generate:
            result = tr.translate_and_review(
                "Ella se quedo en casa.", model="lia-hymt2:1.8b-q8", previous="Contexto.")
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["previous"], "Contexto.")
        self.assertEqual(result["translation"], "She stayed home.")

    def test_quantity_retries_then_rejects(self):
        with patch.object(tr, "generate", return_value="Millions died.") as generate:
            with self.assertRaises(ValueError):
                tr.translate_segment("Murieron miles de millones.", model="qwen3:4b")
        self.assertEqual(generate.call_count, 2)

    def test_quantity_valid_second_attempt(self):
        with patch.object(tr, "generate", side_effect=["Millions died.", "Billions died."]):
            result = tr.translate_segment("Murieron miles de millones.", model="qwen3:4b")
        self.assertEqual(result["translation"], "Billions died.")

    def test_symbol_g_in_source_is_allowed(self):
        self.assertEqual(tr.review_damage_reasons(
            "The ring bore the letter G.", "The ring bore G: Gadianes.",
            "El anillo mostraba la letra G."), [])

    def test_g_inside_name_does_not_exempt_broken_name(self):
        reasons = tr.review_damage_reasons(
            "The Gadianes won.", "The G: Gadianes won.", "Los Gadianes ganaron.")
        self.assertTrue(reasons)


import unittest
from app.services.translation.consistency_checker import fidelity_warnings, paragraph_fidelity_warnings


class FidelityWarningTests(unittest.TestCase):
    def codes(self, source, target):
        return {w["code"] for w in fidelity_warnings(source, target)}

    def test_recorded_errors(self):
        cases = [
            ("miles de millones murieron", "Millions died.", "quantity_scale"),
            ("Acaso esto no era una atrocidad;", "Perhaps this wasn't cruelty.", "rhetorical_negation"),
            ("permitieron tenernos más controlados", "allowed us to maintain more control over our lives", "control_roles"),
            ("dirigir los países por debajo del agua", "govern the countries underwater", "literal_idiom"),
            ("Sustancias vertidas en aquellas bombas", "Substances poured into those bombs", "ambiguous_equipment"),
            ("elegir de entre una lista de diez personas", "choose ten people", "selection_quantity"),
            ("Una fuerza hizo que no tomara una mala decision y me uniera.", "A force made me not make a bad decision and join.", "negation_scope"),
        ]
        for source, target, code in cases:
            with self.subTest(code=code):
                self.assertIn(code, self.codes(source, target))

    def test_clear_negation_is_not_flagged(self):
        self.assertEqual(self.codes("Ella no llego.", "She didn't arrive."), set())

    def test_literal_water_and_real_bombs_not_flagged(self):
        self.assertEqual(self.codes("Nadaron por debajo del agua.", "They swam underwater."), set())
        self.assertEqual(self.codes("Las bombas explotaron.", "The bombs exploded."), set())

    def test_political_idiom_spelling_variants(self):
        source = "Dirigir los paises por debajo del agua."
        for target in ("Govern the countries underwater.",
                       "Govern the countries under water.",
                       "Govern the countries under  water.",
                       "Govern the countries beneath water.",
                       "Govern the countries beneath the water."):
            with self.subTest(target=target):
                self.assertIn("literal_idiom", self.codes(source, target))
        self.assertNotIn("literal_idiom", self.codes(
            "Nadaron por debajo del agua.", "They swam under water."))
        self.assertNotIn("literal_idiom", self.codes(
            source, "Govern the countries behind the scenes."))

    def test_paragraph_mapping_preserves_blanks(self):
        result = paragraph_fidelity_warnings("Titulo\n\nmiles de millones", "Title\n\nMillions")
        self.assertEqual(result[0]["source_paragraph"], 2)

    def test_unaligned_text_does_not_guess(self):
        result = paragraph_fidelity_warnings("Uno\nDos", "One and two")
        self.assertEqual(result[0]["code"], "fidelity_alignment_pending")
        self.assertNotIn("source_paragraph", result[0])



if __name__ == "__main__":
    unittest.main()
