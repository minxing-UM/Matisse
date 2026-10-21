"""Personality editing uses isolated files, never the author's real persona."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, ollama_client, web_server
from app.backend.personality_manager import PersonalityConflict, PersonalityManager, startup_personality


class PersonalityTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def require_customization(self):
        path = ollama_client.CONFIG_FILE
        settings = json.loads(path.read_text(encoding="utf-8"))
        settings["personality_required"] = True
        path.write_text(json.dumps(settings), encoding="utf-8")

    def test_empty_install_requires_customization_before_messages_or_interactions(self):
        self.require_customization()
        self.assertFalse(self.app.personality_payload()["configured"])
        self.assertTrue(self.app.personality_payload()["required"])
        before = self.app.emotion_manager.get_state()
        for operation in (lambda: self.app.send_message(self.chat_id, "你好"),
                          lambda: self.app.perform_interaction(self.chat_id, "hug"),
                          lambda: ollama_client.ask_matisse([{"role": "user", "content": "你好"}])):
            with self.assertRaisesRegex((ValueError, RuntimeError), "customize"):
                operation()
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertIsNone(self.app._generate_thought())

    def restart_backend(self):
        # Model a new process: the editor cannot clear this cache at runtime.
        startup_personality.cache_clear()
        self.app = web_server.MatisseWebApp()

    def test_saved_and_external_changes_only_apply_after_backend_restart(self):
        self.require_customization()
        first = self.app.personality_payload()
        original = "# 自己的角色\n\n温柔，有自己的见解。\n"
        saved = self.app.update_personality(original, first["revision"])
        self.assertEqual(saved["content"], original)
        self.assertEqual(ollama_client.PERSONALITY_FILE.read_text(encoding="utf-8"), original)
        self.assertTrue(saved["configured"])
        self.assertTrue(saved["restart_required"])
        self.assertFalse(saved["active_configured"])
        with self.assertRaisesRegex(ValueError, "restart"):
            self.app.send_message(self.chat_id, "你好")
        self.restart_backend()
        self.assertFalse(self.app.personality_payload()["restart_required"])
        self.assertTrue(self.app.personality_payload()["active_configured"])
        self.app.update_personality("网页里保存的新人格", self.app.personality_payload()["revision"])
        external = "# Another custom character\n说话简短，喜欢天文学。"
        ollama_client.PERSONALITY_FILE.write_text(external, encoding="utf-8", newline="\n")
        self.assertTrue(self.app.personality_payload()["restart_required"])
        with patch.object(ollama_client, "chat", return_value=SimpleNamespace(message=SimpleNamespace(content=fixtures.turn("今晚想聊聊星星吗？").model_dump_json()))) as model:
            with patch.object(PersonalityManager, "read", side_effect=AssertionError("generation must not reread the file")):
                self.app.send_message(self.chat_id, "你好")
                ollama_client.ask_matisse([], autonomous_instruction="分享一个新想法。")
            for call in model.call_args_list:
                prompt = call.kwargs["messages"][0]["content"]
                self.assertEqual(prompt.count(original), 1)
                self.assertNotIn(external, prompt)
                self.assertNotIn("网页里保存的新人格", prompt)
            self.restart_backend()
            ollama_client.ask_matisse([{"role": "user", "content": "你好"}])
        self.assertIn(external, model.call_args.kwargs["messages"][0]["content"])
        self.assertNotIn(original, model.call_args.kwargs["messages"][0]["content"])
        self.assertFalse(self.app.personality_payload()["restart_required"])

    def test_saving_the_same_active_content_does_not_require_restart(self):
        content = "# 当前角色\n说话简洁。"
        self.app.update_personality(content, self.app.personality_payload()["revision"])
        self.restart_backend()
        saved = self.app.update_personality(content, self.app.personality_payload()["revision"])
        self.assertFalse(saved["restart_required"])

    def test_reverting_to_active_content_clears_pending_restart(self):
        first = self.app.update_personality("原来的人格", self.app.personality_payload()["revision"])
        self.restart_backend()
        changed = self.app.update_personality("新的人格", first["revision"])
        self.assertTrue(changed["restart_required"])
        restored = self.app.update_personality("原来的人格", changed["revision"])
        self.assertFalse(restored["restart_required"])

    def test_invalid_or_stale_saves_do_not_replace_the_file(self):
        initial = self.app.personality_payload()
        saved = self.app.update_personality("# 我的角色\n开朗。", initial["revision"])
        for invalid in (None, [], "  \n", "x" * 16001):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(ValueError):
                self.app.update_personality(invalid, saved["revision"])
        ollama_client.PERSONALITY_FILE.write_text("外部编辑器保存的新版本", encoding="utf-8")
        with self.assertRaises(PersonalityConflict):
            self.app.update_personality("旧窗口的草稿", saved["revision"])
        self.assertEqual(self.app.personality_payload()["content"], "外部编辑器保存的新版本")

    def test_atomic_write_failure_preserves_original_and_removes_temporary_file(self):
        old = self.app.update_personality("旧的人格", self.app.personality_payload()["revision"])
        with patch("app.backend.personality_manager.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.app.update_personality("新的人格", old["revision"])
        self.assertEqual(self.app.personality_payload()["content"], "旧的人格")
        self.assertEqual(list(ollama_client.PERSONALITY_FILE.parent.glob("*.tmp")), [])

    def test_saving_does_not_rewrite_history_memories_or_settings_and_payloads_stay_separate(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        saved = self.app.update_personality("仅存在本机的自定义人格", self.app.personality_payload()["revision"])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file() and p != ollama_client.PERSONALITY_FILE}
        self.assertEqual(before, after)
        self.assertNotIn(saved["content"], str(self.app.settings_payload()))
        self.assertNotIn(saved["content"], str(self.app.create_demo_chat("T3")))

    def test_demo_can_run_without_personal_customization_and_does_not_read_personal_prompt(self):
        self.require_customization()
        with patch.object(ollama_client, "load_personality", side_effect=AssertionError("must not read personal persona")), patch.object(ollama_client, "chat", return_value=SimpleNamespace(message=SimpleNamespace(content=fixtures.turn("你好，很高兴认识你。").model_dump_json()))):
            demo = self.app.create_demo_chat("T3")
            result = self.app.send_demo_message(demo["id"], "你好")
        self.assertEqual(result["messages"][-1]["content"], "你好，很高兴认识你。")

    def test_bom_file_can_be_read_without_changing_its_revision(self):
        path = self.root / "bom.md"
        path.write_text("# Character\n自己的角色", encoding="utf-8-sig", newline="\n")
        manager = PersonalityManager(path)
        snapshot = manager.read()
        self.assertEqual(snapshot["content"], "# Character\n自己的角色")
        self.assertEqual(snapshot, manager.read())


if __name__ == "__main__":
    unittest.main()
