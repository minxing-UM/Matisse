"""Self-initiated remarks use completed context instead of answering old turns."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, ollama_client, thought_manager
from app.backend.ollama_client import AutonomousTurn


class ThoughtNoveltyTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def stub_model(self, turn):
        self.stack.enter_context(patch.object(ollama_client, "load_personality", return_value="Test character"))
        self.stack.enter_context(patch.object(ollama_client, "CanonManager", return_value=SimpleNamespace(context_for=lambda _: "")))
        response = SimpleNamespace(message=SimpleNamespace(content=turn.model_dump_json()))
        return self.stack.enter_context(patch.object(ollama_client, "chat", return_value=response))

    def test_completed_history_is_quoted_data_and_current_task_comes_last(self):
        model = self.stub_model(fixtures.turn("我忽然想到画名也可以是一种留白。"))
        history = [{"role": "user", "content": "怎样给画起名字？"},
                   {"role": "assistant", "content": "可以从色彩、氛围或主题里选择。"}]
        original = copy.deepcopy(history)
        result = ollama_client.ask_matisse(history, autonomous_instruction="SHARE A NEW THOUGHT")
        sent = model.call_args.kwargs["messages"]
        self.assertEqual([message["role"] for message in sent], ["system"])
        prompt = sent[0]["content"]
        self.assertIn("[COMPLETED CONVERSATION — BACKGROUND DATA]", prompt)
        self.assertIn("怎样给画起名字？", prompt)
        self.assertIn("可以从色彩、氛围或主题里选择。", prompt)
        self.assertGreater(prompt.index("SHARE A NEW THOUGHT"), prompt.index("[END OF COMPLETED BACKGROUND]"))
        self.assertEqual(history, original)
        self.assertEqual(result.user_affect.source, "none")

    def test_normal_reply_still_uses_live_dialogue_roles(self):
        model = self.stub_model(fixtures.turn("可以从色彩、氛围或主题里选择。"))
        ollama_client.ask_matisse([{"role": "user", "content": "怎样给画起名字？"}])
        self.assertEqual([message["role"] for message in model.call_args.kwargs["messages"]], ["system", "user"])
        self.assertNotIn("COMPLETED CONVERSATION", model.call_args.kwargs["messages"][0]["content"])

    def test_autonomous_runtime_does_not_ask_to_continue_the_user_topic(self):
        fixtures.IsolatedAppTest.due_now(self)
        self.app.life_manager.state["active_topic"] = "怎样给画起名字？"
        with patch.object(thought_manager, "ask_matisse", return_value=fixtures.turn("我忽然想到画名也可以是一种留白。")) as model:
            self.app._generate_thought()
        self.assertNotIn("[CONVERSATION CONTINUITY]", model.call_args.kwargs["runtime_context"])
        self.assertIn("过去的问答已经结束", model.call_args.kwargs["autonomous_instruction"])

    def test_repeated_completed_answer_is_suppressed_without_emotion_change(self):
        original = "给画起名字时，可以先看看它的主要颜色，再想想你希望表达的氛围。"
        chat = chat_manager.ChatManager.load(self.chat_id)
        chat.add_message("user", "怎样给画起名字？")
        chat.add_message("assistant", original)
        before = self.app.emotion_manager.get_state()
        fixtures.IsolatedAppTest.due_now(self)
        with patch.object(thought_manager, "ask_matisse", return_value=fixtures.turn("我想再说一句，" + original, happiness=5)):
            self.assertIsNone(self.app._generate_thought())
        self.assertEqual(len(chat_manager.ChatManager.load(self.chat_id).messages), 2)
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))

    def test_new_association_on_same_topic_is_allowed(self):
        original = "给画起名字时，可以先看看它的主要颜色，再想想你希望表达的氛围。"
        new = "我忽然觉得画名像一扇半开的门，留一点没说透的地方，也许更能让人停下来。"
        self.assertFalse(self.app.thought_manager.repeats_recent(new, [original]))
        chat = chat_manager.ChatManager.load(self.chat_id)
        chat.add_message("user", "怎样给画起名字？")
        chat.add_message("assistant", original)
        fixtures.IsolatedAppTest.due_now(self)
        with patch.object(thought_manager, "ask_matisse", return_value=fixtures.turn(new)):
            self.assertEqual(self.app._generate_thought(), new)
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages[-1]["content"], new)

    def test_no_new_thought_can_be_silent_without_retry_or_state_change(self):
        quiet = AutonomousTurn(**{**fixtures.turn("").model_dump(), "has_new_thought": False})
        model = self.stub_model(quiet)
        fixtures.IsolatedAppTest.due_now(self)
        before = self.app.emotion_manager.get_state()
        recent_before = copy.deepcopy(self.app.thought_manager.state["recent"])
        self.assertIsNone(self.app._generate_thought())
        self.assertEqual(model.call_count, 1)
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertEqual(self.app.emotion_manager.get_state(), before)
        self.assertEqual(self.app.thought_manager.state["recent"], recent_before)
        self.assertEqual(self.app.memory_manager.queue["turns"], [])
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))

    def test_quiet_flag_discards_a_draft_instead_of_publishing_it(self):
        quiet = AutonomousTurn(**{**fixtures.turn("没有新内容，只是在复述。", happiness=7).model_dump(),
                                  "has_new_thought": False})
        self.stub_model(quiet)
        result = ollama_client.ask_matisse([], autonomous_instruction="A quiet moment.")
        self.assertFalse(result.has_new_thought)
        self.assertEqual(result.reply, "")


if __name__ == "__main__":
    unittest.main()
