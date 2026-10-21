"""Use only temporary repositories and stubbed model outputs."""

import json
import io
import random
import shutil
import threading
import time
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.backend import canon_manager, chat_manager, emotion_manager, life_manager, memory_manager
from app.backend import ollama_client, thought_manager, trait_manager, web_manager, web_server
from app.backend import main as cli
from app.backend.generation_queue import GenerationQueue
from app.backend.ollama_client import EmotionDelta, MatisseTurn, UserAffect
from app.backend.thought_manager import ThoughtManager
from app.backend.personality_manager import startup_personality


def turn(text, happiness=1):
    return MatisseTurn(reply=text, mood_label="calm", user_affect=UserAffect.neutral(), emotion_delta=EmotionDelta(
        happiness=happiness, anger=0, hurt=0, sadness=0, loneliness=0, excitement=0
    ))


@contextmanager
def isolated_directory():
    # Inherit the workspace ACL: Python 3.14's Windows mkdtemp mode 0700
    # creates a DACL that excludes the desktop sandbox's restricted token.
    parent = Path(__file__).resolve().parent
    root = parent / f".test-state-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        root.resolve().relative_to(parent)
        shutil.rmtree(root)


class IsolatedAppTest(unittest.TestCase):
    def setUp(self):
        startup_personality.cache_clear()
        self.addCleanup(startup_personality.cache_clear)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(isolated_directory())
        config = self.root / "config"
        config.mkdir()
        (config / "settings.json").write_text(json.dumps({
            "model": "test-model", "memory_enabled": False,
            "memory_embedding_enabled": False, "memory_summary_mode": "manual"
        }), encoding="utf-8")
        (config / "proactive.json").write_text(json.dumps({
            **life_manager.DEFAULT_CONFIG, "wake_hour": 0, "sleep_hour": 0
        }), encoding="utf-8")
        paths = {
            chat_manager: {"CHAT_DIR": "chats"},
            emotion_manager: {"STATE_DIR": "state", "EMOTIONS_FILE": "state/emotions.json", "RUNTIME_FILE": "state/runtime.json"},
            memory_manager: {"MEMORY_DIR": "memories", "MEMORIES_FILE": "memories/memories.json", "QUEUE_FILE": "memories/queue.json", "EMBEDDINGS_FILE": "memories/embeddings.json"},
            life_manager: {"DIR": "activities", "STATE": "activities/state.json", "JOURNAL": "activities/journal.json", "OUTBOX": "activities/outbox.json", "CONFIG": "config/proactive.json"},
            thought_manager: {"STATE_FILE": "activities/thoughts.json"},
            ollama_client: {"CONFIG_FILE": "config/settings.json", "PERSONALITY_FILE": "config/personality.md"},
            canon_manager: {"CANON_FILE": "config/character_canon.json"},
            cli: {"PERSONALITY_FILE": "config/personality.md"},
            trait_manager: {"TRAITS_FILE": "config/traits.json"},
            web_manager: {"WORLD_FILE": "knowledge/world.json", "CONFIG_FILE": "config/web.json"},
            web_server: {"CHAT_DIR": "chats", "AVATAR_DIR": "assets", "AVATAR_META_FILE": "assets/portrait.json", "CONFIG_FILE": "config/settings.json", "PERSONALITY_FILE": "config/personality.md"}
        }
        for module, names in paths.items():
            for name, relative in names.items():
                self.stack.enter_context(patch.object(module, name, self.root / relative))
        self.stack.enter_context(patch.object(web_server, "start_idle_worker"))
        self.app = web_server.MatisseWebApp()
        self.chat_id = self.app.create_chat()["id"]
        self.app.thought_manager.rng = random.Random(13)

    def due_now(self):
        self.app.thought_manager.state["next_thought_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()

    def test_schedule_persists_and_stays_in_range(self):
        manager = self.app.thought_manager
        now = datetime(2026, 10, 20, 12)
        self.assertFalse(manager.due(self.app.life_manager, now))
        deadline = datetime.fromisoformat(manager.state["next_thought_at"])
        self.assertGreaterEqual(deadline, now + timedelta(minutes=1))
        self.assertLessEqual(deadline, now + timedelta(minutes=10))
        restored = ThoughtManager(path=manager.path)
        self.assertEqual(restored.state["next_thought_at"], deadline.isoformat())
        self.assertFalse(restored.due(self.app.life_manager, now + timedelta(seconds=1)))
        self.assertTrue(restored.due(self.app.life_manager, deadline))

    def test_awake_and_quiet_hours_pause_without_catchup_spam(self):
        life = self.app.life_manager
        life.wake_hour, life.sleep_hour = 6, 2
        self.assertTrue(life.in_awake_hours(datetime(2026, 10, 20, 23)))
        self.assertTrue(life.in_awake_hours(datetime(2026, 10, 20, 1)))
        self.assertFalse(life.in_awake_hours(datetime(2026, 10, 20, 2)))
        self.assertTrue(life.in_awake_hours(datetime(2026, 10, 20, 6)))
        self.due_now()
        self.assertFalse(self.app.thought_manager.due(life, datetime(2026, 10, 20, 4)))
        self.assertIsNone(self.app.thought_manager.state["next_thought_at"])
        self.assertFalse(self.app.thought_manager.due(life, datetime(2026, 10, 20, 12)))
        life.quiet_hours_enabled = True
        life.quiet_start_hour, life.quiet_end_hour = 11, 13
        self.assertFalse(self.app.thought_manager.due(life, datetime(2026, 10, 20, 12)))

    def test_angles_rotate_and_recent_text_is_in_prompt(self):
        manager = self.app.thought_manager
        manager.state["recent"] = [
            {"angle": "connection", "text": "昨天说到的书让我想到一个问题。"},
            {"angle": "curiosity", "text": "我想试试从另一个角度理解那个故事。"}
        ]
        angle, prompt = manager.prompt(self.app.life_manager)
        self.assertNotIn(angle, ("connection", "curiosity"))
        self.assertIn(manager.state["recent"][0]["text"], prompt)
        self.assertIn(self.app.life_manager.long_term_goal, prompt)

    def test_thought_is_assistant_only_and_does_not_create_memory_turn(self):
        self.due_now()
        with patch.object(thought_manager, "ask_matisse", return_value=turn("我想从另一个角度聊聊故事里的选择。")) as model:
            with self.app._generation_lock.background() as admitted:
                self.assertTrue(admitted)
                self.app._generate_thought()
        chat = chat_manager.ChatManager.load(self.chat_id)
        self.assertEqual([message["role"] for message in chat.messages], ["assistant"])
        self.assertTrue(chat.messages[0]["metadata"]["autonomous"])
        self.assertIn("autonomous_instruction", model.call_args.kwargs)
        self.assertEqual(self.app.memory_manager.queue["turns"], [])
        self.assertIsNone(self.app.emotion_manager.runtime["last_interaction"])
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))

    def test_duplicate_is_suppressed_before_emotion_update(self):
        self.due_now()
        text = "我想从另一个角度理解昨天那个故事里的选择。"
        self.app.thought_manager.state["recent"] = [{"angle": "curiosity", "text": text}]
        before = self.app.emotion_manager.get_state()
        with patch.object(thought_manager, "ask_matisse", return_value=turn(text)):
            self.assertIsNone(self.app._generate_thought())
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertEqual(before, self.app.emotion_manager.get_state())
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))

    def test_model_failure_releases_queue_and_backs_off(self):
        self.due_now()
        with patch.object(thought_manager, "ask_matisse", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                with self.app._generation_lock.background():
                    self.app._generate_thought()
        self.assertIsNone(self.app._generation_lock.snapshot()["kind"])
        self.assertEqual(chat_manager.ChatManager.load(self.chat_id).messages, [])
        self.assertFalse(self.app.thought_manager.due(self.app.life_manager))

    def test_question_waits_for_thought_and_sees_updated_state(self):
        self.due_now()
        thought_started = threading.Event()
        finish_thought = threading.Event()
        answer_started = threading.Event()
        finish_answer = threading.Event()
        errors = []
        results = []
        contexts = []

        def thought_model(*args, **kwargs):
            thought_started.set()
            if not finish_thought.wait(3):
                raise TimeoutError("test thought")
            return turn("我刚想到一个关于故事的新角度。", happiness=2)

        def answer_model(messages, runtime_context):
            contexts.append((messages, runtime_context))
            answer_started.set()
            if not finish_answer.wait(3):
                raise TimeoutError("test answer")
            return turn("现在回答你刚刚的问题。")

        def background():
            try:
                with self.app._generation_lock.background() as admitted:
                    if admitted:
                        self.app._generate_thought()
            except Exception as error:
                errors.append(error)

        def foreground():
            try:
                results.append(self.app.send_message(self.chat_id, "能解释一下这个问题吗？"))
            except Exception as error:
                errors.append(error)

        with patch.object(thought_manager, "ask_matisse", side_effect=thought_model), patch.object(web_server, "ask_matisse", side_effect=answer_model):
            first = threading.Thread(target=background)
            second = threading.Thread(target=foreground)
            first.start()
            self.assertTrue(thought_started.wait(2))
            second.start()
            try:
                deadline = time.monotonic() + 2
                while not self.app._generation_lock.snapshot()["waiting"] and time.monotonic() < deadline:
                    time.sleep(0.001)
                self.assertEqual(self.app._generation_lock.snapshot()["waiting"], 1)
                self.assertFalse(answer_started.is_set())
                finish_thought.set()
                self.assertTrue(answer_started.wait(2))
                # Polling must show the completed remark while the answer is still running.
                snapshot = self.app.claim_proactive_message(self.chat_id)
                self.assertEqual([m["role"] for m in snapshot["chat"]["messages"]], ["assistant", "user"])
                self.assertEqual(contexts[0][0][-2]["content"], "我刚想到一个关于故事的新角度。")
                self.assertEqual(contexts[0][0][-1]["content"], "能解释一下这个问题吗？")
                self.assertIn(f'happiness: {self.app.emotion_manager.get_state()["happiness"]}', contexts[0][1])
            finally:
                finish_thought.set()
                finish_answer.set()
                first.join(3)
                second.join(3)
        self.assertFalse(errors, errors)
        self.assertEqual([m["role"] for m in results[0]["chat"]["messages"]], ["assistant", "user", "assistant"])
        self.assertEqual(len(self.app.memory_manager.queue["turns"]), 1)

    def test_polling_is_idempotent_and_targets_original_chat(self):
        self.due_now()
        with patch.object(thought_manager, "ask_matisse", return_value=turn("我有一个新的小想法。")):
            self.app._generate_thought()
        other = self.app.create_chat()["id"]
        self.assertEqual(self.app.claim_proactive_message(other)["chat"]["messages"], [])
        self.app.claim_proactive_message(self.chat_id)
        self.app.claim_proactive_message(self.chat_id)
        self.assertEqual(len(chat_manager.ChatManager.load(self.chat_id).messages), 1)

    def test_invalid_settings_have_no_partial_effect(self):
        before = (self.root / "config/settings.json").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            self.app.update_settings({"context_length": 16000, "proactive": {"thought_min_minutes": 10, "thought_max_minutes": 1}})
        self.assertEqual(before, (self.root / "config/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(self.app.life_manager.thought_min_minutes, 1)

    def test_goal_and_schedule_settings_round_trip(self):
        result = self.app.update_settings({"proactive": {
            "long_term_goal": "珍惜关系，也培养自己的阅读兴趣。",
            "thought_min_minutes": 2, "thought_max_minutes": 7,
            "wake_hour": 7, "sleep_hour": 23
        }})
        self.assertEqual(result["proactive"]["thought_min_minutes"], 2)
        restored = life_manager.LifeManager()
        self.assertEqual(restored.long_term_goal, "珍惜关系，也培养自己的阅读兴趣。")
        self.assertEqual(restored.sleep_hour, 23)

    def test_generated_remarks_cannot_be_regenerated_as_answers(self):
        self.due_now()
        with patch.object(thought_manager, "ask_matisse", return_value=turn("我有一个新的小想法。")):
            self.app._generate_thought()
        message = chat_manager.ChatManager.load(self.chat_id).messages[-1]
        with self.assertRaisesRegex(ValueError, "self-initiated"):
            self.app.regenerate_reply(self.chat_id, message["id"])

    def test_autonomous_instruction_is_system_context_not_a_fake_user(self):
        response = SimpleNamespace(message=SimpleNamespace(content=turn("一个真实可见的小念头。").model_dump_json()))
        with patch.object(ollama_client, "chat", return_value=response) as model, patch.object(ollama_client, "load_personality", return_value="Test character"), patch.object(ollama_client, "CanonManager", return_value=SimpleNamespace(context_for=lambda text: "")):
            ollama_client.ask_matisse([], autonomous_instruction="An autonomous task.")
        sent = model.call_args.kwargs["messages"]
        self.assertEqual([message["role"] for message in sent], ["system"])
        self.assertIn("An autonomous task.", sent[0]["content"])

    def test_cli_new_chat_and_exit_use_the_same_queue_and_scheduler(self):
        with patch.object(cli, "start_idle_worker") as worker, patch("builtins.input", side_effect=["/new", "/exit"]), patch("sys.stdout", new_callable=io.StringIO):
            cli.main()
        self.assertIsInstance(worker.call_args.kwargs["generation_lock"], GenerationQueue)
        self.assertTrue(callable(worker.call_args.kwargs["thought_callback"]))
        self.assertEqual(len(list((self.root / "chats").glob("chat_*.json"))), 3)


class GenerationQueueTest(unittest.TestCase):
    def test_fifo_reentrancy_and_no_background_overtaking(self):
        queue = GenerationQueue()
        order = []
        threads = []
        with queue.background() as admitted:
            self.assertTrue(admitted)
            for number in range(3):
                def job(index=number):
                    with queue:
                        with queue:
                            order.append(index)
                        with queue.background() as extra:
                            self.assertFalse(extra)
                thread = threading.Thread(target=job)
                thread.start()
                threads.append(thread)
                deadline = time.monotonic() + 2
                while queue.snapshot()["waiting"] != number + 1 and time.monotonic() < deadline:
                    time.sleep(0.001)
                self.assertEqual(queue.snapshot()["waiting"], number + 1)
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(order, [0, 1, 2])
        self.assertIsNone(queue.snapshot()["kind"])


if __name__ == "__main__":
    unittest.main()
