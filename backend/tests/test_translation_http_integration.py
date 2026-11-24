"""Integration with real HTTP transport and SQLite, simulated model responses.

This suite intentionally makes no claim about real Ollama inference quality.
All prose and model replies are synthetic test data, not user manuscripts.
"""
import json
import os
import tempfile
import threading
import time
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import literary_step4 as routes
from app.core.config import settings
from app.core.database import connect, initialize
from app.services.translation import step4_store as store


class ModelFixtureServer(ThreadingHTTPServer):
    daemon_threads = True


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            result = {"capabilities": ["completion"]}
        else:
            prompt = payload["prompt"]
            if payload.get("raw"):
                source = prompt.split("without any additional explanation:\n", 1)[1].split("<｜hy_Assistant｜>")[0]
            elif payload.get("format"):
                source = json.loads(prompt)["source"] if prompt.startswith("{") else prompt
            else:
                source = prompt.rsplit("\n\n", 1)[1]
            self.server.calls.append({"source": source, "payload": payload})
            outputs = self.server.outputs[source]
            text = outputs.pop(0) if len(outputs) > 1 else outputs[0]
            result = {"done_reason": "stop", "eval_count": 10,
                      "response": json.dumps({"translation": text}) if payload.get("format") else text}
        encoded = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class TranslationHTTPIntegrationTests(unittest.TestCase):
    first = "Ella cerro la puerta y salio al bosque."
    second = "El chico miro hacia el bosque silencioso."
    translated_first = "She closed the door and walked into the forest."
    translated_second = "The boy looked toward the silent forest."

    @classmethod
    def setUpClass(cls):
        cls.server = ModelFixtureServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        settings.data_dir = Path(self.directory.name)
        self.env = patch.dict(os.environ, {
            "LIA_OLLAMA_URL": f"http://127.0.0.1:{self.server.server_address[1]}",
            "LIA_EDITORIAL_REVIEW_POLICY": "selective",
        })
        self.env.start()
        self.server.calls = []
        self.server.outputs = {self.first: [self.translated_first], self.second: [self.translated_second]}
        self.source = self.first + "\n\n***\n" + self.second + "\n"
        initialize()
        store.initialize_step4()
        with connect() as db:
            db.execute("INSERT INTO projects VALUES ('p','Test','now')")
            db.execute("INSERT INTO manuscripts VALUES ('m','p','novel.txt',?,'now')", (self.source,))
        with routes._progress_lock:
            routes._progress.clear()
            routes._controls.clear()
            routes._jobs.clear()
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)
        self.base = "/api/projects/p/manuscripts/m"

    def tearDown(self):
        self.client.close()
        self.env.stop()
        settings.data_dir = self.old_data_dir
        self.directory.cleanup()

    def translate(self, model="lia-hymt2:1.8b-q8"):
        return self.client.post(self.base + "/translate-chapter", json={"chapter_index": 0, "model": model})

    def test_native_http_retry_then_exact_layout_and_saved_version(self):
        self.server.outputs[self.first] = ["Here is the translation: She left.", self.translated_first]
        response = self.translate()
        self.assertEqual(response.status_code, 201, response.text)
        detail = self.client.get(self.base + "/versions/" + response.json()["id"]).json()
        self.assertEqual(detail["translated_text"], self.translated_first + "\n\n***\n" + self.translated_second + "\n")
        self.assertEqual(detail["source_text"], self.source)
        self.assertEqual(len(self.server.calls), 3)
        self.assertTrue(all(call["payload"].get("raw") for call in self.server.calls))
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM literary_segment_checkpoints").fetchone()[0], 0)

    def test_incomplete_chapter_has_no_version_and_resumes_only_missing(self):
        self.server.outputs[self.first] = ["She opened the:"]
        failed = self.translate()
        self.assertEqual(failed.status_code, 422, failed.text)
        self.assertEqual(self.client.get(self.base + "/versions").json(), [])
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM literary_segment_checkpoints").fetchone()[0], 1)
        counts = Counter(call["source"] for call in self.server.calls)
        self.assertEqual(counts[self.first], 4)  # 2 model attempts in each of 2 piece attempts.
        self.assertEqual(counts[self.second], 1)
        self.server.outputs[self.first] = [self.translated_first]
        self.server.calls.clear()
        resumed = self.translate()
        self.assertEqual(resumed.status_code, 201, resumed.text)
        self.assertEqual(resumed.json()["resumed_segments"], 1)
        self.assertEqual([call["source"] for call in self.server.calls], [self.first])

    def test_qwen25_plain_http_does_not_run_unnecessary_review(self):
        response = self.translate("qwen2.5:3b")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(self.server.calls), 2)
        for call in self.server.calls:
            self.assertNotIn("format", call["payload"])
            self.assertNotIn("system", call["payload"])

    def test_qwen3_structured_http_contract_is_preserved(self):
        response = self.translate("qwen3:4b")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(self.server.calls), 2)
        self.assertTrue(all("format" in call["payload"] for call in self.server.calls))

    def test_async_job_completes_only_after_version_is_available(self):
        job = str(uuid4())
        start = self.client.post(self.base + "/translation-jobs", json={
            "chapter_index": 0, "model": "lia-hymt2:1.8b-q8", "job_id": job})
        self.assertEqual(start.status_code, 202, start.text)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            progress = self.client.get(self.base + "/translation-progress/" + job).json()
            if progress["state"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual(progress["state"], "completed", progress)
        version_id = progress["result"]["id"]
        self.assertEqual(self.client.get(self.base + "/versions/" + version_id).status_code, 200)

    def test_existing_version_gets_annotations_without_rewriting(self):
        saved = store.add_version("p", "m", 0, "Chapter", self.first,
                                  "She wanted to: pass the test.", [])
        before = saved["created_at"]
        detail = self.client.get(self.base + "/versions/" + saved["id"]).json()
        self.assertEqual(detail["created_at"], before)
        self.assertEqual(detail["translated_text"], "She wanted to: pass the test.")
        self.assertIn("broken_function_word_colon", {w["code"] for w in detail["warnings"]})
        with connect() as db:
            row = db.execute("SELECT translated_text,warnings_json FROM literary_versions WHERE id=?", (saved["id"],)).fetchone()
            self.assertEqual(tuple(row), ("She wanted to: pass the test.", "[]"))

    def test_corrupt_cached_segment_is_not_resumed(self):
        key = store.checkpoint_key("p", "m", 0, self.source, "lia-hymt2:1.8b-q8", {})
        store.save_segment_checkpoint(key, 0, self.first, "Here is the translation: She left.", [])
        response = self.translate()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["resumed_segments"], 0)
        self.assertEqual(len(self.server.calls), 2)


if __name__ == "__main__":
    unittest.main()
