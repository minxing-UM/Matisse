"""Grounded affect, deterministic resonance and entry-point integration."""

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

import test_spontaneous_thoughts as fixtures
from app.backend import chat_manager, emotion_manager, ollama_client, thought_manager, web_server
from app.backend import main as cli
from app.backend.ollama_client import EmotionDelta, MatisseTurn, UserAffect


def affect(evidence="我现在很难过", **changes):
    return UserAffect(**{**UserAffect.neutral().model_dump(), "source": "current_user",
                         "confidence": 0.9, "sadness": 0.8, "evidence": evidence, **changes})


def reply(feeling=None, **delta):
    values = {name: 0 for name in emotion_manager.MODEL_EMOTIONS}
    return MatisseTurn(reply="听见你这样说，我也有些难过。我们可以慢慢聊。", mood_label="mixed",
                       emotion_delta=EmotionDelta(**{**values, **delta}),
                       user_affect=feeling or UserAffect.neutral())


class ResonanceTest(unittest.TestCase):
    setUp = fixtures.IsolatedAppTest.setUp

    def test_affect_schema_requires_valid_grounded_fields(self):
        self.assertIn("user_affect", MatisseTurn.model_json_schema()["required"])
        for key in ("confidence", "happiness", "sadness", "excitement"):
            for value in (-0.1, 1.1, float("nan"), float("inf")):
                with self.assertRaises(ValidationError):
                    affect(**{key: value})
        with self.assertRaises(ValidationError):
            affect(source="diagnosis")

    def test_sadness_is_mirrored_without_hurt_or_anger(self):
        manager = self.app.emotion_manager
        before = manager.get_state()
        report = manager.apply_turn_emotions({}, affect().model_dump(), "我现在很难过")
        self.assertGreater(report["emotion_delta_resonance"]["sadness"], 0)
        self.assertGreater(manager.get_state()["sadness"], before["sadness"])
        for name in ("happiness", "anger", "hurt", "loneliness", "excitement"):
            self.assertEqual(manager.get_state()[name], before[name])

    def test_happiness_excitement_and_mixed_feelings_can_coexist(self):
        manager = self.app.emotion_manager
        manager.emotions["current"]["sadness"] = 12
        happy = affect("我拿到录取了，好开心好期待！", sadness=0, happiness=0.9, excitement=0.8)
        before = manager.get_state()
        manager.apply_turn_emotions({}, happy.model_dump(), happy.evidence)
        self.assertGreater(manager.get_state()["happiness"], before["happiness"])
        self.assertGreater(manager.get_state()["excitement"], before["excitement"])
        self.assertEqual(manager.get_state()["sadness"], 12)
        mixed = affect("我开心也有点舍不得", sadness=0.7, happiness=0.7)
        report = manager.apply_turn_emotions({}, mixed.model_dump(), mixed.evidence)
        self.assertGreater(report["emotion_delta_resonance"]["sadness"], 0)
        self.assertGreater(report["emotion_delta_resonance"]["happiness"], 0)

    def test_non_current_uncertain_and_ungrounded_affect_has_no_resonance(self):
        manager = self.app.emotion_manager
        message = "我现在很难过"
        for source in ("none", "other", "quoted", "hypothetical", "unclear"):
            self.assertFalse(any(manager.resonance_delta(affect(source=source).model_dump(), message).values()))
        for feeling in (affect(confidence=0.59), affect(confidence=0.8), affect(confidence=0.899), affect(evidence=""), affect(evidence=" "),
                        affect(evidence="这是上轮的原文")):
            self.assertFalse(any(manager.resonance_delta(feeling.model_dump(), message).values()))

    def test_empathy_controls_strength_and_can_disable_resonance(self):
        manager = self.app.emotion_manager
        manager.emotions["traits"]["empathy"] = 0
        self.assertFalse(any(manager.resonance_delta(affect().model_dump(), "我现在很难过").values()))
        manager.emotions["traits"]["empathy"] = 0.2
        low = manager.resonance_delta(affect().model_dump(), "我现在很难过")["sadness"]
        manager.emotions["traits"]["empathy"] = 0.9
        high = manager.resonance_delta(affect().model_dump(), "我现在很难过")["sadness"]
        self.assertGreater(high, low)

    def test_other_person_and_conditional_evidence_are_conservatively_rejected(self):
        manager = self.app.emotion_manager
        for evidence in ("我朋友今天很伤心，但我自己心情平静", "我的同事很伤心",
                         "她现在感到悲伤", "如果以后考试没过我会伤心", "假设我很开心",
                         "My friend is sad", "If I fail I will feel sad", "She feels sad"):
            signal = affect(evidence=evidence, confidence=0.99)
            self.assertFalse(any(manager.resonance_delta(signal.model_dump(), evidence).values()), evidence)
        message = "我朋友今天很伤心，我自己也觉得难过"
        signal = affect(evidence="我自己也觉得难过")
        self.assertGreater(manager.resonance_delta(signal.model_dump(), message)["sadness"], 0)

    def test_quoted_and_code_evidence_cannot_trigger_even_if_model_mislabels_it(self):
        manager = self.app.emotion_manager
        for message in ('请翻译：“我现在很难过”。', 'Translate "我现在很难过".',
                        "Translate '我现在很难过'.", '翻译‘我现在很难过’。',
                        '台词「我现在很难过」', '台词『我现在很难过』',
                        '打印 `我现在很难过`', '```text\n我现在很难过\n```',
                        '~~~\n我现在很难过\n~~~', '> 我现在很难过\n这是引用。'):
            self.assertFalse(any(manager.resonance_delta(affect().model_dump(), message).values()), message)
        # A real feeling outside a quotation remains eligible, including contractions.
        message = '看完“结局”后，我现在很难过'
        self.assertGreater(manager.resonance_delta(affect().model_dump(), message)["sadness"], 0)
        signal = affect(evidence="I'm sad", sadness=0.8)
        self.assertGreater(manager.resonance_delta(signal.model_dump(), "I'm sad today")["sadness"], 0)

    def test_direct_and_resonance_are_not_added_twice(self):
        manager = self.app.emotion_manager
        report = manager.apply_turn_emotions({"sadness": 3}, affect().model_dump(), "我现在很难过")
        self.assertEqual(report["emotion_delta_combined"]["sadness"], 3)
        factor = (0.5 + manager.get_traits()["emotional_sensitivity"]) * (1 - 0.5 * manager.get_traits()["emotional_inertia"])
        self.assertEqual(manager.get_state()["sadness"], round(3 * factor, 2))
        report = manager.apply_turn_emotions({"sadness": -5}, affect().model_dump(), "我现在很难过")
        self.assertLess(report["emotion_delta_combined"]["sadness"], 0)

    def test_repeated_resonance_is_bounded_and_does_not_erase_high_mood(self):
        manager = self.app.emotion_manager
        signal = affect(sadness=1, confidence=1).model_dump()
        with patch.object(manager, "save"):
            for _ in range(500):
                manager.apply_turn_emotions({}, signal, "我现在很难过")
        self.assertGreater(manager.get_state()["sadness"], 70)
        self.assertLessEqual(manager.get_state()["sadness"], 80)
        manager.emotions["current"]["sadness"] = 95
        manager.apply_turn_emotions({}, signal, "我现在很难过")
        self.assertEqual(manager.get_state()["sadness"], 95)

    def test_web_turn_persists_report_and_next_turn_sees_resonance(self):
        with patch.object(web_server, "ask_matisse", side_effect=[reply(affect()), reply()]) as model:
            result = self.app.send_message(self.chat_id, "我现在很难过")
            sadness = result["mood"]["values"]["sadness"]
            saved = chat_manager.ChatManager.load(self.chat_id).messages[-1]["metadata"]
            self.assertEqual(saved["user_affect"]["source"], "current_user")
            self.assertGreater(saved["emotion_delta_resonance"]["sadness"], 0)
            self.assertEqual(saved["emotion_delta_proposed"]["sadness"], 0)
            self.app.send_message(self.chat_id, "我们慢慢聊")
            self.assertIn(f"- sadness: {sadness}/100", model.call_args.kwargs["runtime_context"])
            self.assertEqual(self.app.mood()["values"]["sadness"], sadness)

    def test_failed_generation_changes_no_emotions(self):
        before = self.app.emotion_manager.get_state()
        with patch.object(web_server, "ask_matisse", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                self.app.send_message(self.chat_id, "我现在很难过")
        self.assertEqual(self.app.emotion_manager.get_state(), before)

    def test_regeneration_does_not_repeat_resonance(self):
        with patch.object(web_server, "ask_matisse", return_value=reply(affect())):
            result = self.app.send_message(self.chat_id, "我现在很难过")
            sadness = self.app.mood()["values"]["sadness"]
            self.app.regenerate_reply(self.chat_id, result["chat"]["messages"][-1]["id"])
        saved = chat_manager.ChatManager.load(self.chat_id).messages[-1]["metadata"]
        self.assertFalse(saved["resonance_enabled"])
        self.assertFalse(any(saved["emotion_delta_resonance"].values()))
        self.assertEqual(self.app.mood()["values"]["sadness"], sadness)

    def test_autonomous_generation_cannot_reabsorb_the_previous_user(self):
        with patch.object(web_server, "ask_matisse", return_value=reply(affect())):
            self.app.send_message(self.chat_id, "我现在很难过")
        sadness = self.app.mood()["values"]["sadness"]
        fixtures.IsolatedAppTest.due_now(self)
        with patch.object(thought_manager, "ask_matisse", return_value=reply(affect())):
            self.app._generate_thought()
        self.assertEqual(self.app.mood()["values"]["sadness"], sadness)

    def test_single_call_prompt_and_autonomous_output_guard(self):
        response = SimpleNamespace(message=SimpleNamespace(content=reply(affect()).model_dump_json()))
        with patch.object(ollama_client, "chat", return_value=response) as model, \
                patch.object(ollama_client, "load_personality", return_value="Test character"), \
                patch.object(ollama_client, "CanonManager", return_value=SimpleNamespace(context_for=lambda _: "")):
            turn = ollama_client.ask_matisse([{"role": "user", "content": "我现在很难过"}])
            self.assertEqual(turn.user_affect.source, "current_user")
            self.assertEqual(model.call_count, 1)
            self.assertIn("[AFFECTIVE RESONANCE]", model.call_args.kwargs["messages"][0]["content"])
            turn = ollama_client.ask_matisse([], autonomous_instruction="A quiet thought.")
            self.assertEqual(turn.user_affect, UserAffect.neutral())

    def test_cli_also_applies_resonance(self):
        with patch.object(cli, "start_idle_worker"), \
                patch("builtins.input", side_effect=["我现在很难过", "/exit"]), \
                patch.object(cli, "ask_matisse", return_value=reply(affect())), \
                patch("sys.stdout", new_callable=io.StringIO):
            cli.main()
        self.assertGreater(emotion_manager.EmotionManager().get_state()["sadness"], 0)


if __name__ == "__main__":
    unittest.main()
