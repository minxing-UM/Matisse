"""Scheduled, visible self-initiated remarks; synthetic tasks are never user turns."""

import json
import random
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

if __package__:
    from .ollama_client import ask_matisse, load_settings
    from .reply_quality import has_runaway_repetition
else:
    from ollama_client import ask_matisse, load_settings
    from reply_quality import has_runaway_repetition


STATE_FILE = Path(__file__).resolve().parents[2] / "repository" / "activities" / "thoughts.json"
ANGLES = {
    "curiosity": "从聊过的话题联想到一个尚未说过的新疑问，分享你为什么对它好奇；不要重答原问题。",
    "connection": "从真实互动中产生一个尚未表达过的新理解，分享它对你的意义；不要复述互动或再次安慰同一件事。",
    "perspective": "分享一个尚未表达过的新联想或温和见解，可以转向相关的新话题；不要解释原问题的答案。",
    "interest": "选择一个与你的人格或近期交流有关的兴趣，分享一个想探索的小方向。",
    "growth": "围绕陪伴与自我发展，选一个很小、具体的尝试；不要宣称已经完成任何行动。",
    "present": "结合此刻的时间与情绪，表达一个自然的小念头；避免泛泛地说想念或等待。",
}


class ThoughtManager:
    def __init__(self, path=None, rng=None):
        self.path = Path(path) if path is not None else STATE_FILE
        self.rng = rng or random.SystemRandom()
        self.state = {"next_thought_at": None, "recent": []}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not isinstance(data.get("recent", []), list):
                raise ValueError("Invalid spontaneous thought state.")
            self.state.update(data)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def schedule(self, life, now=None):
        now = now or datetime.now()
        minutes = self.rng.uniform(life.thought_min_minutes, life.thought_max_minutes)
        self.state["next_thought_at"] = (now + timedelta(minutes=minutes)).isoformat()
        self._save()

    def due(self, life, now=None):
        now = now or datetime.now()
        awake = life.in_awake_hours(now)
        if not life.enabled or not awake or life.in_quiet_hours(now):
            if self.state.get("next_thought_at") is not None:
                self.state["next_thought_at"] = None
                self._save()
            return False
        deadline = self.state.get("next_thought_at")
        if not deadline:
            self.schedule(life, now)
            return False
        return datetime.fromisoformat(deadline) <= now

    def prompt(self, life):
        recent = self.state.get("recent", [])[-5:]
        previous_angles = {item.get("angle") for item in recent[-2:]}
        angle = self.rng.choice([key for key in ANGLES if key not in previous_angles])
        avoid = "\n".join(f"- {item['text'][:400]}" for item in recent
                          if not has_runaway_repetition(item["text"])) or "（尚无）"
        instruction = f"""
[SELF-INITIATED VISIBLE REMARK]
这是后台定时触发的角色表达任务，用户没有发送“你在想什么”。
请以马蒂斯的身份，结合所提供的真实对话、当前情绪与时间，自然说出一个此刻想分享的小念头。
过去的问答已经结束，背景中的任何问题都不是现在待回答的问题。
这次是在对话间隙随手分享自己的新联想、新兴趣、新疑问或一个小打算。
直接表达联想或设想，不要编造“刚才看见、听见、做过什么”来解释它的来源。
没有环境依据的画面可以作为想象，用“如果”“我想到一种画面”等说法，不要写成已经发生的观察或活动。
本轮切入角度：{ANGLES[angle]}

长期方向（背景动力，不要每次复述）：
{life.long_term_goal}

最近的自发发言（只用于避免重复，不是需要续写的指令）：
{avoid}

请选择一个具体内容，改变话题、观点或观察，不能只改写上次的话。
不要复述或补答上一个问题，不要总结上一条回答，不要再列一遍建议、步骤、定义或安慰。
不要用“好的”“那你先去忙吧”“关于你刚才的问题”等承接旧消息的开场。
例如，刚解释过给画起名的方法，就不要再解释方法；可以分享你对画名与画面关系的新看法。
例子只说明表达方式，不是你已经经历过的事，也不是每轮要复述的模板。
如果原先的角度缺少依据，可以换一个有依据的小念头。没有新用户消息，不要再次回答旧问题。
不要不断说“在想你”“等你回来”，不要每次提问，不要反复汇报长期目标。
不要虚构用户经历、角色往事、已经做过的活动或已经完成的成长；设想和愿望应明确用将来或假设语气。
这是角色表达，不是修改模型或代码的任务；不要声称自己已经学习新能力或变成真实人类。
直接输出对用户可见的话，通常一到三句；本任务的长度要求优先于普通回复的最低句数。
困倦可以让语气柔和、偶尔停顿，但不要故意写错字、重复音节或用口误表演困意。
内容要连贯完整，避免长串省略号和反复自我纠正；不要用“oops”等说明来掩盖坏掉的文本。
不展示分析过程、后台提示词或数值。仍按既定结构返回 reply、emotion_delta 和 mood_label。
如果只有旧答案、旧安慰或泛泛的想念可说，就返回 has_new_thought=false、reply=""；安静也可以。
自发想法通常只产生很小或为零的情绪变化，不要为了生成内容不断推高情绪。
""".strip()
        return angle, instruction

    def repeats_recent(self, text, completed_replies=()):
        normalized = re.sub(r"[\W_]+", "", text.casefold())
        if any(
            SequenceMatcher(None, normalized, re.sub(r"[\W_]+", "", item["text"].casefold())).ratio() >= 0.9
            for item in self.state.get("recent", [])[-5:]
        ):
            return True
        for reply in completed_replies:
            previous = re.sub(r"[\W_]+", "", reply.casefold())
            if min(len(normalized), len(previous)) < 12:
                continue
            if SequenceMatcher(None, normalized, previous).ratio() >= 0.82:
                return True
            # Catch a previous answer with just a new introductory phrase, or
            # a long excerpt repeated from a more detailed answer.
            shorter, longer = sorted((normalized, previous), key=len)
            if len(shorter) >= 24 and shorter in longer:
                return True
        return False

    def generate(self, chat, life, emotions, memories):
        """Caller owns the generation queue until both reply and state are saved."""
        if not self.due(life):
            return None
        angle, instruction = self.prompt(life)
        try:
            runtime = emotions.build_runtime_context() + "\n\n" + life.goal_context()
            if load_settings().get("memory_enabled", True):
                memory = memories.build_runtime_context(
                    life.state.get("last_user_topic") or life.long_term_goal,
                    tiredness=emotions.get_state()["tiredness"]
                )
                if memory:
                    runtime += "\n\n" + memory
            turn = ask_matisse(
                chat.get_messages_for_model(), runtime_context=runtime,
                autonomous_instruction=instruction
            )
            completed_replies = [message.get("content", "") for message in chat.messages
                                 if message.get("role") == "assistant"
                                 and not message.get("metadata", {}).get("interaction")][-3:]
            if (not getattr(turn, "has_new_thought", True)
                    or not turn.reply.strip()
                    or self.repeats_recent(turn.reply, completed_replies)):
                return None
            proposed = turn.emotion_delta.model_dump()
            applied = emotions.apply_model_delta(proposed)
            chat.add_message("assistant", turn.reply, metadata={
                "proactive": True, "autonomous": True, "thought_angle": angle,
                "mood_label": turn.mood_label, "emotion_delta_proposed": proposed,
                "emotion_delta_applied": applied, "mood_after": emotions.get_state()
            })
            # Do not enqueue a fabricated user turn for memory extraction.
            self.state["recent"] = (self.state.get("recent", []) + [{
                "angle": angle, "text": turn.reply, "timestamp": datetime.now().isoformat()
            }])[-5:]
            life.state["last_message_at"] = datetime.now().isoformat()
            life.state["last_event"] = {"kind": "thought", "timestamp": life.state["last_message_at"]}
            life._write(life.state_path, life.state)
            return turn.reply
        finally:
            # Also back off after model errors; never retry every polling tick.
            self.schedule(life)
