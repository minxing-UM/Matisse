"""Language selection reaches model instructions without rewriting stored content."""

import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, ollama_client, web_server
from app.backend.language import ReplyLanguageError, validate_reply_language


class LanguageTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def stub_model(self, reply="It's good to see you. How was your day?"):
        self.stack.enter_context(patch.object(ollama_client, "load_personality", return_value="始终用中文说话。"))
        self.stack.enter_context(patch.object(ollama_client, "CanonManager", return_value=SimpleNamespace(context_for=lambda _: "")))
        response = SimpleNamespace(message=SimpleNamespace(content=fixtures.turn(reply).model_dump_json()))
        return self.stack.enter_context(patch.object(ollama_client, "chat", return_value=response))

    def test_language_defaults_persists_and_rejects_bad_values_without_changes(self):
        self.assertEqual(self.app.language_payload(), {"language": "zh"})
        before = ollama_client.load_settings()
        self.app.set_language("en")
        self.assertEqual(self.app.language_payload(), {"language": "en"})
        after = ollama_client.load_settings()
        self.assertEqual({key: value for key, value in after.items() if key != "language"}, before)
        for value in (None, "fr", "EN", [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.app.set_language(value)
        self.assertEqual(ollama_client.load_settings(), after)
        self.app.set_language("zh")
        self.assertEqual(self.app.settings_payload()["language"], "zh")

    def test_selected_language_overrides_persona_but_keeps_original_message(self):
        model = self.stub_model()
        self.app.set_language("en")
        message = "我今天很开心"
        ollama_client.ask_matisse([{"role": "user", "content": message}])
        sent = model.call_args.kwargs["messages"]
        prompt = sent[0]["content"]
        self.assertIn("Write the user-facing reply in English", prompt)
        self.assertGreater(prompt.index("SELECTED REPLY LANGUAGE"), prompt.index("始终用中文"))
        self.assertIn("never translate that evidence", prompt)
        self.assertNotIn("three connected Chinese", prompt)
        self.assertEqual(sent[-1]["content"], message)
        self.app.set_language("zh")
        ollama_client.ask_matisse([{"role": "user", "content": "Hello"}])
        self.assertIn("Write the user-facing reply in Simplified Chinese", model.call_args.kwargs["messages"][0]["content"])

    def test_autonomous_language_instruction_comes_after_chinese_task(self):
        model = self.stub_model()
        self.app.set_language("en")
        ollama_client.ask_matisse([], autonomous_instruction="现在分享一个小念头，用中文写。")
        prompt = model.call_args.kwargs["messages"][-1]["content"]
        self.assertGreater(prompt.index("SELECTED REPLY LANGUAGE"), prompt.index("现在分享一个小念头"))
        self.assertIn("Write the user-facing reply in English", prompt)

    def test_demo_uses_selected_language_and_keeps_relationship_and_mood(self):
        model = self.stub_model()
        self.app.set_language("en")
        chat = self.app.create_demo_chat("T2")
        result = self.app.send_demo_message(chat["id"], "你今天怎么样？")
        prompt = model.call_args.kwargs["messages"][0]["content"]
        self.assertIn("当前关系为 T2", prompt)
        self.assertIn("Write the user-facing reply in English", prompt)
        self.assertEqual(result["tier"], "T2")
        self.assertEqual(result["messages"][0]["content"], "你今天怎么样？")
        self.assertEqual(result["messages"][1]["content"], "It's good to see you. How was your day?")
        self.assertGreater(result["mood"]["current"]["happiness"], chat["mood"]["current"]["happiness"])

    def test_switching_language_does_not_rewrite_personal_chat_memory_or_emotions(self):
        chat = chat_manager.ChatManager.load(self.chat_id)
        chat.add_message("user", "你好，这是原文。")
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*")
                  if path.is_file() and path != web_server.CONFIG_FILE}
        self.app.set_language("en")
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*")
                 if path.is_file() and path != web_server.CONFIG_FILE}
        self.assertEqual(after, before)

    def test_fixed_interactions_and_memory_confirmation_follow_language(self):
        self.app.set_language("en")
        for action in web_server.INTERACTION_ACTIONS:
            with self.subTest(action=action["id"]):
                result = self.app.perform_interaction(self.chat_id, action["id"])
                self.assertFalse(re.search(r"[\u4e00-\u9fff]", result["reply"]))
        result = self.app.summarize_pending_memories(self.chat_id)
        self.assertFalse(re.search(r"[\u4e00-\u9fff]", result["reply"]))
        self.app.set_language("zh")
        result = self.app.perform_interaction(self.chat_id, "hug")
        self.assertIn("拥抱", result["reply"])

    def test_wrong_language_retries_without_saving_or_applying_the_failed_draft(self):
        model = self.stub_model()
        self.app.set_language("zh")
        wrong = fixtures.turn("A quiet walk and some warm tea sound like a lovely celebration.", happiness=9)
        accepted = fixtures.turn("散散步、喝杯茶，听起来是很舒服的庆祝方式。", happiness=0)
        model.side_effect = [SimpleNamespace(message=SimpleNamespace(content=turn.model_dump_json()))
                             for turn in (wrong, accepted)]
        result = self.app.send_message(self.chat_id, "I might celebrate with a quiet walk and some tea.")
        self.assertEqual(result["reply"], accepted.reply)
        self.assertEqual(model.call_count, 2)
        retry = model.call_args.kwargs["messages"]
        self.assertIn("RETRY: USE THE SELECTED REPLY LANGUAGE", retry[0]["content"])
        self.assertNotIn(wrong.reply, str(retry))
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages[-1]["content"], accepted.reply)

    def test_language_check_allows_names_code_quotations_and_translation_examples(self):
        for reply in ("Matisse", "```python\nprint('Hello, this is an English code sample')\n```",
                      '原句是 “A quiet walk and some warm tea sound like a lovely celebration.”。'):
            validate_reply_language(reply, {"language": "zh"})
        validate_reply_language("I would like to celebrate with a quiet walk and some tea.",
                                {"language": "zh"}, "请翻译这句话成英文")
        validate_reply_language('The message says “今天我感到非常开心，因为项目终于完成了”。', {"language": "en"})
        validate_reply_language("阿尔伯特·爱因斯坦", {"language": "en"})
        with self.assertRaises(ReplyLanguageError):
            validate_reply_language("今天我感到非常开心，因为项目终于完成了。", {"language": "en"})


if __name__ == "__main__":
    unittest.main()
