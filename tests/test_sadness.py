"""Sadness integration using isolated state files and stubbed model outputs."""

import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from pydantic import ValidationError

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, emotion_manager, thought_manager, web_server
from app.backend.ollama_client import EmotionDelta, MatisseTurn, UserAffect


class SadnessTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def test_legacy_state_upgrades_without_resetting_values(self):
        legacy = copy.deepcopy(emotion_manager.DEFAULT_EMOTIONS)
        legacy["version"] = 1
        for section in ("current", "baseline", "half_life_hours"):
            del legacy[section]["sadness"]
        legacy["current"]["hurt"] = 42.3
        legacy["baseline"]["happiness"] = 31
        legacy["traits"]["emotional_inertia"] = 0.9
        emotion_manager.EMOTIONS_FILE.write_text(json.dumps(legacy), encoding="utf-8")
        manager = emotion_manager.EmotionManager()
        self.assertEqual(manager.get_state()["sadness"], 0)
        self.assertEqual(manager.emotions["baseline"]["sadness"], 0)
        self.assertEqual(manager.emotions["half_life_hours"]["sadness"], 12)
        self.assertEqual(manager.get_state()["hurt"], 42.3)
        self.assertEqual(manager.emotions["baseline"]["happiness"], 31)
        self.assertEqual(manager.get_traits()["emotional_inertia"], 0.9)
        saved = json.loads(emotion_manager.EMOTIONS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved, manager.emotions)
        self.assertEqual(saved["version"], 2)

    def test_upgrade_preserves_existing_sadness_and_custom_decay(self):
        manager = self.app.emotion_manager
        manager.emotions["current"]["sadness"] = 27
        manager.emotions["baseline"]["sadness"] = 2
        manager.emotions["half_life_hours"]["sadness"] = 18
        manager.save()
        reloaded = emotion_manager.EmotionManager()
        self.assertEqual(reloaded.get_state()["sadness"], 27)
        self.assertEqual(reloaded.emotions["baseline"]["sadness"], 2)
        self.assertEqual(reloaded.emotions["half_life_hours"]["sadness"], 18)

    def test_model_requires_a_valid_sadness_delta(self):
        values = {name: 0 for name in emotion_manager.MODEL_EMOTIONS}
        schema = EmotionDelta.model_json_schema()
        self.assertEqual(set(schema["required"]), set(emotion_manager.MODEL_EMOTIONS))
        for invalid in (None, 11, -11, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                EmotionDelta(**{**values, "sadness": invalid})
        del values["sadness"]
        with self.assertRaises(ValidationError):
            EmotionDelta(**values)

    def test_sadness_delta_is_independent_persisted_and_bounded(self):
        manager = self.app.emotion_manager
        before = manager.get_state()
        applied = manager.apply_model_delta({"sadness": 5})
        self.assertGreater(applied["sadness"], 0)
        for name in emotion_manager.MODEL_EMOTIONS:
            if name != "sadness":
                self.assertEqual(manager.get_state()[name], before[name])
        self.assertEqual(emotion_manager.EmotionManager().get_state(), manager.get_state())
        self.assertIn(f'- sadness: {manager.get_state()["sadness"]}/100', manager.build_runtime_context())
        # The existing fixed interactions omit sadness; omission means no change.
        score = manager.get_state()["sadness"]
        manager.apply_model_delta(web_server.INTERACTION_DELTAS["hug"])
        self.assertEqual(manager.get_state()["sadness"], score)
        manager.emotions["current"]["sadness"] = 99
        manager.apply_model_delta({"sadness": 100})
        self.assertEqual(manager.get_state()["sadness"], 100)
        manager.emotions["current"]["sadness"] = 1
        manager.apply_model_delta({"sadness": -100})
        self.assertEqual(manager.get_state()["sadness"], 0)

    def test_startup_decay_uses_sadness_baseline_and_half_life(self):
        manager = self.app.emotion_manager
        manager.emotions["current"]["sadness"] = 42
        manager.emotions["baseline"]["sadness"] = 2
        manager.runtime["last_interaction"] = "2026-10-21T00:00:00"
        with patch.object(emotion_manager, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 21, 12)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            manager.update_on_startup()
        self.assertEqual(manager.get_state()["sadness"], 22)
        self.assertEqual(emotion_manager.EmotionManager().get_state()["sadness"], 22)

    def test_reply_saves_sadness_and_passes_it_to_next_turn(self):
        values = {name: 0 for name in emotion_manager.MODEL_EMOTIONS}
        first = MatisseTurn(reply="听到这个结局，我也有些难过。", mood_label="sad",
                            user_affect=UserAffect.neutral(),
                            emotion_delta=EmotionDelta(**{**values, "sadness": 4}))
        with patch.object(web_server, "ask_matisse", side_effect=[first, fixtures.turn("嗯，我还记得刚才的感受。")]) as model:
            reply = self.app.send_message(self.chat_id, "这个故事有个悲伤的结局。")
            sadness = reply["mood"]["values"]["sadness"]
            self.assertGreater(sadness, 0)
            saved = chat_manager.ChatManager.load(self.chat_id).messages[-1]["metadata"]
            self.assertEqual(saved["emotion_delta_proposed"]["sadness"], 4)
            self.assertEqual(saved["mood_after"]["sadness"], sadness)
            self.app.send_message(self.chat_id, "我们慢慢聊。")
            self.assertIn(f"- sadness: {sadness}/100", model.call_args.kwargs["runtime_context"])

    def test_spontaneous_remark_and_guess_mood_support_sadness(self):
        fixtures.IsolatedAppTest.due_now(self)
        values = {name: 0 for name in emotion_manager.MODEL_EMOTIONS}
        turn = MatisseTurn(reply="那个故事的结局还让我有点怅然。", mood_label="sad",
                           user_affect=UserAffect.neutral(),
                           emotion_delta=EmotionDelta(**{**values, "sadness": 1}))
        with patch.object(thought_manager, "ask_matisse", return_value=turn):
            self.app._generate_thought()
        self.assertGreater(self.app.mood()["values"]["sadness"], 0)
        self.app.emotion_manager.emotions["current"]["sadness"] = 100
        self.assertIn("难过", self.app._interaction_reply("guess_mood"))


if __name__ == "__main__":
    unittest.main()
