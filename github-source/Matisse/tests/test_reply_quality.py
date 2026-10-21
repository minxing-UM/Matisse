"""Regression coverage for runaway repetition in scheduled and normal replies."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, ollama_client
from app.backend.reply_quality import has_runaway_repetition


BROKEN_REPLY = "今天其实挺平静的，虽然没什么波澜，甚至" + "连着" * 80 + "_ (oops, 困意里念叨。)"


def response(turn):
    return SimpleNamespace(message=SimpleNamespace(content=turn.model_dump_json()))


class RepetitionCheckTest(unittest.TestCase):
    def test_reported_short_loop_and_repeated_paragraphs_are_rejected(self):
        for text in (BROKEN_REPLY, "连着 " * 40, "哈" * 50,
                     "我忽然想到，故事里的选择也许可以换一个角度看。" * 5):
            self.assertTrue(has_runaway_repetition(text), text[:40])

    def test_normal_emphasis_laughter_pauses_numbers_and_code_are_allowed(self):
        for text in ("今天……其实过得挺平静的。慢慢来，慢慢来。哈哈哈哈，真有意思。",
                     "我喜欢你，也喜欢这样的下午。", "." * 100, "0" * 100,
                     "重复字符串示例：`" + "连着" * 80 + "`。",
                     "```python\nvalue = '" + "连着" * 80 + "'\n```",
                     "~~~text\n" + "连着" * 80 + "\n~~~"):
            self.assertFalse(has_runaway_repetition(text), text[:40])


class ReplyQualityIntegrationTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def stub_model(self, outputs):
        self.stack.enter_context(patch.object(ollama_client, "load_personality", return_value="Test character"))
        self.stack.enter_context(patch.object(ollama_client, "CanonManager", return_value=SimpleNamespace(context_for=lambda _: "")))
        return self.stack.enter_context(patch.object(ollama_client, "chat", side_effect=outputs))

    def test_retry_rewrites_without_feeding_the_broken_draft_back(self):
        model = self.stub_model([response(fixtures.turn(BROKEN_REPLY)), response(fixtures.turn("我刚想到一个新的角度。"))])
        result = ollama_client.ask_matisse([{"role": "user", "content": "聊聊今天的想法。"}])
        self.assertEqual(result.reply, "我刚想到一个新的角度。")
        self.assertEqual(model.call_count, 2)
        first, second = [call.kwargs for call in model.call_args_list]
        self.assertGreater(first["options"]["repeat_penalty"], 1)
        self.assertLess(second["options"]["temperature"], first["options"]["temperature"])
        self.assertIn("[RETRY: REWRITE DEGENERATE PROSE]", second["messages"][0]["content"])
        self.assertNotIn("连着" * 20, str(second["messages"]))
        self.assertEqual(second["messages"][-1]["content"], "聊聊今天的想法。")

    def test_scheduled_reply_retries_and_only_applies_the_accepted_emotion(self):
        fixtures.IsolatedAppTest.due_now(self)
        model = self.stub_model([response(fixtures.turn(BROKEN_REPLY, happiness=10)),
                                 response(fixtures.turn("我想从另一个角度理解故事里的选择。", happiness=0))])
        before = self.app.emotion_manager.get_state()
        result = self.app._generate_thought()
        self.assertEqual(model.call_count, 2)
        self.assertTrue(result)
        self.assertLessEqual(model.call_args.kwargs["options"]["num_predict"], 1024)
        saved = chat_manager.ChatManager.load(self.chat_id).messages
        self.assertEqual(len(saved), 1)
        self.assertNotIn("连着", saved[0]["content"])
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertEqual(self.app.memory_manager.queue["turns"], [])

    def test_two_bad_scheduled_results_publish_nothing_and_reschedule(self):
        fixtures.IsolatedAppTest.due_now(self)
        model = self.stub_model([response(fixtures.turn(BROKEN_REPLY))] * 2)
        before = self.app.emotion_manager.get_state()
        with self.assertRaisesRegex(RuntimeError, "异常重复"):
            with self.app._generation_lock.background():
                self.app._generate_thought()
        self.assertEqual(model.call_count, 2)
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))
        self.assertIsNone(self.app._generation_lock.snapshot()["kind"])

    def test_two_bad_foreground_results_leave_no_message_or_memory_turn(self):
        self.stub_model([response(fixtures.turn(BROKEN_REPLY))] * 2)
        before = self.app.emotion_manager.get_state()
        with self.assertRaisesRegex(RuntimeError, "异常重复"):
            self.app.send_message(self.chat_id, "我有一个问题。")
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertEqual(self.app.memory_manager.queue["turns"], [])

    def test_history_filter_keeps_user_content_and_saved_history_intact(self):
        model = self.stub_model([response(fixtures.turn("现在给你一个连贯的回答。"))])
        chat = chat_manager.ChatManager.load(self.chat_id)
        chat.add_message("assistant", BROKEN_REPLY)
        chat.add_message("user", "请解释这段异常输出：" + BROKEN_REPLY)
        history = chat.get_messages_for_model()
        original = copy.deepcopy(history)
        ollama_client.ask_matisse(history)
        sent = model.call_args.kwargs["messages"]
        self.assertEqual([item["role"] for item in sent], ["system", "user"])
        self.assertEqual(sent[-1]["content"], history[-1]["content"])
        self.assertEqual(history, original)
        self.assertEqual(len(chat_manager.ChatManager.load(self.chat_id).messages), 2)

    def test_broken_recent_thought_is_not_a_prompt_example(self):
        manager = self.app.thought_manager
        manager.state["recent"] = [{"angle": "present", "text": BROKEN_REPLY}]
        _, prompt = manager.prompt(self.app.life_manager)
        self.assertNotIn("连着" * 20, prompt)
        self.assertEqual(manager.state["recent"][0]["text"], BROKEN_REPLY)

    def test_streamed_responses_use_the_same_repetition_check(self):
        settings = ollama_client.load_settings()
        self.stack.enter_context(patch.object(ollama_client, "load_settings", return_value={**settings, "stream": True}))
        def chunks(turn):
            content = turn.model_dump_json()
            return iter([SimpleNamespace(message=SimpleNamespace(content=content[:70])),
                         SimpleNamespace(message=SimpleNamespace(content=content[70:]))])
        model = self.stub_model([chunks(fixtures.turn(BROKEN_REPLY)), chunks(fixtures.turn("我有一个具体的小想法。"))])
        result = ollama_client.ask_matisse([])
        self.assertEqual(result.reply, "我有一个具体的小想法。")
        self.assertEqual(model.call_count, 2)


if __name__ == "__main__":
    unittest.main()
