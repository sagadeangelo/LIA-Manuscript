"""Checkpoint regression tests; run from backend: python -m unittest discover -s tests -p test_translation_resume.py"""
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.services.translation import chapter_pipeline as pipeline
from app.services.translation import step4_store as store


class Interrupted(Exception):
    pass


class TranslationResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "checkpoints.sqlite3"

        @contextmanager
        def connect():
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

        self.connection_patch = patch.object(store, "connect", connect)
        self.connection_patch.start()
        store.initialize_step4()
        self.source = "Uno.\n\nDos.\nTres.\n"
        self.key = store.checkpoint_key("project", "manuscript", 4, self.source, "qwen3:4b", {})
        self.calls = []

    def tearDown(self):
        self.connection_patch.stop()
        self.directory.cleanup()

    def generate(self, text, **kwargs):
        self.calls.append(text)
        return {"translation": {"Uno.": "One.", "Dos.": "Two.", "Tres.": "Three."}[text],
                "warnings": [{"type": "test", "message": "notice"}]}

    def test_interrupt_then_new_attempt_resumes_committed_segments(self):
        def stop(completed, total):
            if completed == 2:
                # Connection is reopened here: reporting follows commit.
                self.assertEqual(len(store.load_segment_checkpoints(self.key)), 2)
                raise Interrupted()
        with patch.object(pipeline, "translate_and_review", self.generate):
            with self.assertRaises(Interrupted):
                pipeline.translate_chapter(self.source, {}, "qwen3:4b", stop, checkpoint=self.key)
        self.calls.clear()
        # Fresh invocation and fresh DB connections, with no prior in-memory results.
        progress = []
        with patch.object(pipeline, "translate_and_review", self.generate):
            result = pipeline.translate_chapter(
                self.source, {}, "qwen3:4b", lambda done, total: progress.append((done, total)),
                checkpoint=self.key)
        self.assertEqual(self.calls, ["Tres."])
        self.assertEqual(progress[0], (2, 3))
        self.assertEqual(result["resumed_segments"], 2)
        self.assertEqual(result["translation"], "One.\n\nTwo.\nThree.\n")
        self.assertEqual([w["segment"] for w in result["warnings"]], [1, 2, 3])

    def test_changed_identity_does_not_reuse(self):
        store.save_segment_checkpoint(self.key, 0, "Uno.", "One.", [])
        variants = [
            ("other", "manuscript", 4, self.source, "qwen3:4b", {}),
            ("project", "other", 4, self.source, "qwen3:4b", {}),
            ("project", "manuscript", 5, self.source, "qwen3:4b", {}),
            ("project", "manuscript", 4, self.source + "Cambio.", "qwen3:4b", {}),
            ("project", "manuscript", 4, self.source, "qwen2.5:3b", {}),
            ("project", "manuscript", 4, self.source, "qwen3:4b", {"Uno": "One"}),
        ]
        for identity in variants:
            other_key = store.checkpoint_key(*identity)
            self.assertNotEqual(other_key, self.key)
            self.assertEqual(store.load_segment_checkpoints(other_key), {})
        self.assertEqual(len(store.load_segment_checkpoints(self.key)), 1)
        a = store.checkpoint_key("p", "m", 0, "s", "model", {"a": "b", "c": "d"})
        b = store.checkpoint_key("p", "m", 0, "s", "model", {"c": "d", "a": "b"})
        self.assertEqual(a, b)

    def test_failed_piece_only_is_retried_on_next_attempt(self):
        def fail_second(text, **kwargs):
            if text == "Dos.":
                raise ValueError("invalid translation")
            return self.generate(text, **kwargs)
        with patch.object(pipeline, "translate_and_review", fail_second):
            with self.assertRaises(ValueError):
                pipeline.translate_chapter(self.source, {}, "qwen3:4b", checkpoint=self.key)
        self.assertEqual(set(store.load_segment_checkpoints(self.key)), {0, 2})
        self.calls.clear()
        with patch.object(pipeline, "translate_and_review", self.generate):
            pipeline.translate_chapter(self.source, {}, "qwen3:4b", checkpoint=self.key)
        self.assertEqual(self.calls, ["Dos."])

    def test_invalid_or_wrong_source_checkpoint_is_not_reused(self):
        store.save_segment_checkpoint(self.key, 0, "Wrong.", "One.", [])
        store.save_segment_checkpoint(self.key, 1, "Dos.", "", [])
        store.save_segment_checkpoint(self.key, 2, "Tres.", "Three.\nExtra.", [])
        with patch.object(pipeline, "translate_and_review", self.generate):
            result = pipeline.translate_chapter(self.source, {}, "qwen3:4b", checkpoint=self.key)
        self.assertEqual(self.calls, ["Uno.", "Dos.", "Tres."])
        self.assertEqual(result["resumed_segments"], 0)

    def test_cleanup_preserves_other_checkpoints_and_versions(self):
        store.save_segment_checkpoint(self.key, 0, "Uno.", "One.", [])
        store.save_segment_checkpoint("other", 0, "Otro.", "Other.", [])
        saved = store.add_version("p", "m", 4, "IV", self.source, "English", [])
        store.clear_segment_checkpoints(self.key)
        self.assertEqual(store.load_segment_checkpoints(self.key), {})
        self.assertEqual(len(store.load_segment_checkpoints("other")), 1)
        self.assertEqual(store.get_version("p", "m", saved["id"])["translated_text"], "English")


if __name__ == "__main__":
    unittest.main()
