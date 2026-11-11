"""问答上下文、全视频节点访问、缓存和视频隔离。全部使用离线模型夹具。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scene_fixtures import scene_workspace
from video_hsg.question_answering import VideoQuestionService


class QuestionAnsweringTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.workspace = scene_workspace(self.root)
        self.service = VideoQuestionService(self.workspace)
        self.sent = []
        self.refs = ["track_fixture"]
        def send(endpoint, key, payload):
            self.sent.append(json.loads(json.dumps(payload)))
            if "tools" in payload:
                message = {"content": None, "tool_calls": [{"id": "query_nodes", "type": "function", "function": {
                    "name": "search_graph", "arguments": json.dumps({"query": "", "kind": "entity", "offset": 0})}}]}
            else:
                message = {"content": json.dumps({"answer": "夹具对象持续出现在图中，见 track_fixture。", "node_ids": self.refs})}
            return {"choices": [{"message": message}], "usage": {"total_tokens": 20}}
        self.sender = patch("video_hsg.question_answering.request_analysis", side_effect=send)
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.folder.cleanup()

    def ask(self, question="有哪些实体？", state=None, **changes):
        options = dict(endpoint="https://fixture.invalid/v1", key="qa-secret-not-to-store", model="text-fixture", search_rounds=1)
        options.update(changes)
        video_id = options.pop("video_id", "processed")
        return self.service.answer(video_id, question, state, **options)

    def save_analysis(self, summary="已有整段概括", **request):
        return self.workspace.save(self.workspace.video("processed"), {"summary": summary, "entities": [], "events": []},
                                   "imported", request=request)

    def test_without_analysis_no_analysis_context_or_automatic_full_analysis(self):
        with patch.object(self.workspace, "analyze", side_effect=AssertionError("must not run full analysis")):
            record, state, cached = self.ask()
        self.assertFalse(cached)
        self.assertIsNone(record["analysis_run_id"])
        self.assertNotIn("analysis", record["request"]["qa_context"])
        self.assertEqual(state["turns"][0]["node_ids"], ["track_fixture"])
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn("image_url", json.dumps(self.sent))
        self.assertTrue(all("max_tokens" not in p for p in self.sent))
        self.assertEqual(self.workspace.history("processed"), [])
        self.assertNotIn(b"qa-secret-not-to-store", self.workspace.database.read_bytes())

    def test_existing_analysis_and_selected_record_join_context(self):
        older = self.save_analysis("older overview")
        latest = self.save_analysis("latest overview")
        record, _, _ = self.ask()
        self.assertEqual(record["analysis_run_id"], latest["id"])
        self.assertIn("latest overview", self.sent[0]["messages"][1]["content"])
        self.assertIn("latest overview", self.sent[-1]["messages"][1]["content"])
        record, _, _ = self.ask("再问一个问题", selected_run=older["id"])
        self.assertEqual(record["analysis_run_id"], older["id"])
        self.assertEqual(record["request"]["qa_context"]["analysis"]["result"]["summary"], "older overview")

    def test_followups_and_repeated_dialogue_cache(self):
        first, state, _ = self.ask()
        cached_record, _, cached = self.ask(key="")
        self.assertTrue(cached)
        self.assertEqual(first["id"], cached_record["id"])
        self.assertEqual(len(self.sent), 2)
        second, state, _ = self.ask("它出现了多久？", state)
        self.assertEqual(len(state["turns"]), 2)
        self.assertEqual(second["request"]["qa_context"]["dialogue"][0]["question"], "有哪些实体？")
        self.assertIn(first["result"]["answer"], self.sent[-1]["messages"][1]["content"])

    def test_other_video_and_stale_graph_context_are_not_used(self):
        self.save_analysis("private first video analysis")
        _, state, _ = self.ask()
        original = self.workspace.video("processed")
        self.workspace.register(Path(original["path"]), {**original, "id": "other", "title": "other"})
        record, state, _ = self.ask("second video question", state, video_id="other")
        self.assertEqual(state["video_id"], "other")
        self.assertEqual(len(state["turns"]), 1)
        self.assertNotIn("analysis", record["request"]["qa_context"])
        self.assertNotIn("dialogue", record["request"]["qa_context"])
        graph_hash = self.service.graph("processed").fingerprint
        self.save_analysis("stale graph summary", graph_sha256=graph_hash)
        # 删除之前的非图绑定分析，确保不会回退到这条外部导入记录。
        with self.workspace.connect() as db:
            rows = db.execute("SELECT id,data FROM runs").fetchall()
            for run_id, data in rows:
                if not json.loads(data)["request"].get("graph_sha256"):
                    db.execute("DELETE FROM runs WHERE id=?", (run_id,))
        path = Path(original["scene_bundle"])
        bundle = json.loads(path.read_text(encoding="utf-8"))
        bundle["tracks"][0]["attributes"] = ["changed graph"]
        path.write_text(json.dumps(bundle), encoding="utf-8")
        record, _, _ = self.ask("changed graph question")
        self.assertNotIn("analysis", record["request"]["qa_context"])

    def test_missing_graph_and_cross_video_selected_analysis_block_calls(self):
        with self.assertRaisesRegex(ValueError, "场景图"):
            self.ask(video_id="pending")
        saved = self.save_analysis()
        original = self.workspace.video("processed")
        self.workspace.register(Path(original["path"]), {**original, "id": "other", "title": "other"})
        with self.assertRaisesRegex(ValueError, "其他视频"):
            self.ask(video_id="other", selected_run=saved["id"])
        self.assertEqual(self.sent, [])

    def test_node_browser_pages_entire_video_and_inspects_frames_without_api(self):
        path = Path(self.workspace.video("processed")["scene_bundle"])
        bundle = json.loads(path.read_text(encoding="utf-8"))
        template = bundle["tracks"][0]
        bundle["tracks"] += [{**template, "track_id": f"extra_{i}"} for i in range(25)]
        path.write_text(json.dumps(bundle), encoding="utf-8")
        page = self.service.browse_nodes("processed", "", "entity", 3)
        self.assertEqual(page["total"], 26)
        self.assertEqual(len(page["nodes"]), 6)
        frame_page = self.service.browse_nodes("processed", "", "frame", 2)
        self.assertEqual(frame_page["total"], 12)
        self.assertEqual(frame_page["nodes"][-1]["node_id"], "frame:11")
        frame = self.service.inspect_node("processed", "frame:11")
        self.assertEqual(frame["seconds"], 1.1)
        self.assertEqual(frame["entities"][0]["track_id"], "track_fixture")
        self.assertEqual(frame["record"]["frame_id"], 11)
        self.assertNotIn("image_path", frame["record"])
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.service.inspect_node("processed", "missing")
        self.assertEqual(self.sent, [])

    def test_failed_final_reuses_evidence_without_automatic_retry(self):
        tool_message = {"tool_calls": [{"id": "nodes", "type": "function", "function": {
            "name": "search_graph", "arguments": '{"query":"","kind":"entity"}'}}]}
        replies = [{"choices": [{"message": message}]} for message in [
            tool_message, {"content": "broken json"},
            {"content": json.dumps({"answer": "recovered answer", "node_ids": ["track_fixture"]})}]]
        with patch("video_hsg.question_answering.request_analysis", side_effect=replies) as sender:
            with self.assertRaisesRegex(ValueError, "JSON"):
                self.ask()
            self.assertEqual(sender.call_count, 2)
            record, _, cached = self.ask()
            self.assertFalse(cached)
            self.assertEqual(sender.call_count, 3)
            self.assertNotIn("tools", sender.call_args.args[2])
            self.assertEqual(record["result"]["answer"], "recovered answer")

    def test_unknown_references_are_not_saved_as_success(self):
        self.refs = ["nonexistent_node"]
        with self.assertRaisesRegex(ValueError, "未检索"):
            self.ask()
        with self.workspace.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM qa_turns").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
