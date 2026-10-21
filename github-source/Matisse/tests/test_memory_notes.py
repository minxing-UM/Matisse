import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.backend import ollama_client, web_server
from app.backend.memory_manager import MemoryManager
from app.backend.ollama_client import MemoryCandidate
import test_spontaneous_thoughts as fixtures


def response(value):
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return SimpleNamespace(message=SimpleNamespace(content=content))


def candidate(**changes):
    return {"memory_key": "user.preference.coffee", "content": "你喝咖啡时不加糖。", "importance": 3.23, "reinforcement": 0, **changes}


class MemoryNotesTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def test_scores_allow_zero_and_fraction_but_not_missing_or_invalid(self):
        for score in (0, 0.5, 3.23, 5):
            self.assertEqual(MemoryCandidate(**candidate(importance=score)).importance, score)
        missing = candidate()
        del missing["importance"]
        with self.assertRaises(ValidationError):
            MemoryCandidate(**missing)
        for score in (None, True, -1, 6, float("nan"), float("inf"), "重要", "3分"):
            with self.subTest(score=score), self.assertRaises(ValidationError):
                MemoryCandidate(**candidate(importance=score))

    def test_summary_requests_natural_notes_and_accepts_wrapped_json(self):
        wrapped = '```json\n' + json.dumps({"memories": [candidate()]}, ensure_ascii=False) + '\n```'
        messages = [{"role": "user", "content": "我喝咖啡不加糖。"}]
        with patch.object(ollama_client, "chat", return_value=response(wrapped)) as model:
            summary = ollama_client.summarize_memories(messages)
        self.assertEqual(summary.memories[0].importance, 3.23)
        self.assertEqual(summary.memories[0].content, "你喝咖啡时不加糖。")
        prompt = model.call_args.kwargs["messages"][0]["content"]
        self.assertIn("马蒂斯的视角", prompt)
        self.assertIn("正文必须使用自然中文", prompt)
        self.assertIn("不等于对方已经同意", prompt)

    def test_missing_score_retries_instead_of_inventing_a_default(self):
        invalid = candidate()
        del invalid["importance"]
        with patch.object(ollama_client, "chat", side_effect=[response({"memories": [invalid]}), response({"memories": [candidate(importance=0.5)]})]) as model:
            summary = ollama_client.summarize_memories([])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(summary.memories[0].importance, 0.5)
        self.assertIn("上一次结果没有通过结构校验", model.call_args.kwargs["messages"][0]["content"])

    def test_two_invalid_results_keep_pending_turns_and_report_failure(self):
        memories = self.app.memory_manager
        memories.queue_turn(self.chat_id, "我喝咖啡不加糖。", "记住啦。")
        before = deepcopy(memories.queue["turns"])
        with patch.object(ollama_client, "chat", return_value=response({"memories": [candidate(importance=None)]})):
            with self.assertRaises(RuntimeError):
                memories.summarize_pending(ollama_client.summarize_memories)
        self.assertEqual(memories.queue["turns"], before)
        self.assertEqual(memories.data["memories"], [])
        self.assertEqual(memories.queue["last_summary"]["status"], "failed")
        restored = MemoryManager(embedding_enabled=False)
        self.assertEqual(restored.queue["turns"], before)
        self.assertEqual(self.app.memories_payload()["summary_status"]["status"], "failed")

    def test_missing_memory_list_cannot_silently_consume_queue(self):
        memories = self.app.memory_manager
        memories.queue_turn(self.chat_id, "一句话。", "回复。")
        with patch.object(ollama_client, "chat", return_value=response({})):
            with self.assertRaises(RuntimeError):
                memories.summarize_pending(ollama_client.summarize_memories)
        self.assertEqual(len(memories.queue["turns"]), 1)

    def test_explicit_empty_summary_is_a_success_not_a_scoring_error(self):
        memories = self.app.memory_manager
        memories.queue_turn(self.chat_id, "你好。", "晚上好。")
        with patch.object(ollama_client, "chat", return_value=response({"memories": []})):
            self.assertEqual(memories.summarize_pending(ollama_client.summarize_memories), 0)
        self.assertEqual(memories.queue["turns"], [])
        self.assertEqual(memories.queue["last_summary"]["status"], "success")

    def test_rephrasing_preview_does_not_change_stored_note_or_score(self):
        memories = self.app.memory_manager
        memory = memories.add_manual_memory("User prefers unsweetened coffee.", importance=3.23)
        before = deepcopy(memories.data)
        disk_before = memories._load_json(memories_path := self.root / "memories/memories.json")
        with patch.object(web_server, "rephrase_memory", return_value="你更喜欢不加糖的咖啡。"):
            preview = self.app.preview_memory_wording(memory["id"])
        self.assertEqual(preview["content"], "你更喜欢不加糖的咖啡。")
        self.assertEqual(memories.data, before)
        self.assertEqual(memories._load_json(memories_path), disk_before)
        saved = self.app.update_memory(memory["id"], {"content": preview["content"], "expected_content": preview["original_content"]})
        self.assertEqual(saved["memory"]["importance"], 3.23)
        for field in ("id", "memory_key", "created_at", "expires_at", "occurrences", "status", "category"):
            self.assertEqual(memories.data["memories"][0][field], before["memories"][0][field])

    def test_stale_wording_preview_cannot_overwrite_a_corrected_fact(self):
        memories = self.app.memory_manager
        memory = memories.add_manual_memory("User drinks coffee.")
        memories.update_memory(memory["id"], {"content": "你现在不喝咖啡了。"})
        with self.assertRaisesRegex(ValueError, "已被更新"):
            memories.update_memory(memory["id"], {"content": "你喝咖啡。", "expected_content": "User drinks coffee."})
        self.assertEqual(memories.data["memories"][0]["content"], "你现在不喝咖啡了。")

    def test_missing_old_score_is_distinct_from_zero(self):
        self.assertIsNone(MemoryManager._public_memory({"content": "旧记事"})["importance"])
        self.assertEqual(MemoryManager._public_memory({"content": "小事", "importance": 0})["importance"], 0)

    def test_manual_score_rejects_non_finite_values(self):
        for score in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                self.app.memory_manager.add_manual_memory("你喜欢茶。", importance=score)

    def test_rephrase_uses_a_structured_preview_and_trims_it(self):
        with patch.object(ollama_client, "chat", return_value=response({"content": "  你不喜欢被催着回复。  "})):
            self.assertEqual(ollama_client.rephrase_memory("User dislikes being urged to reply."), "你不喜欢被催着回复。")


if __name__ == "__main__":
    unittest.main()
