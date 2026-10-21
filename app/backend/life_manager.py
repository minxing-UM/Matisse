import json
import re

from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DIR = ROOT_DIR / "repository" / "activities"
STATE = DIR / "state.json"
JOURNAL = DIR / "activity_journal.json"
OUTBOX = DIR / "outbox.json"
CONFIG = ROOT_DIR / "config" / "proactive.json"

DEFAULT_LONG_TERM_GOAL = (
    "成为更理解用户、体贴且有自己见解的伴侣：认真倾听并尊重彼此的边界，"
    "让陪伴建立在真实交流上；同时逐渐探索自己的兴趣、观点和表达方式，"
    "兼顾关系与自我发展，把宏大的方向落实为当下具体的小想法。"
)

DEFAULT_CONFIG = {
    "idle_hours": 0.5,
    "message_cooldown_hours": 6,
    "initiative_check_interval_seconds": 5,
    "initiative_threshold": 100,
    "initiative_cooldown_minutes": 30,
    "initiative_score_decay_per_minute": 0.03,
    "enabled": True,
    "mode": "natural",
    "quiet_hours_enabled": False,
    "quiet_start_hour": 23,
    "quiet_end_hour": 8
}
DEFAULT_CONFIG.update({
    "thought_min_minutes": 1, "thought_max_minutes": 10,
    "wake_hour": 6, "sleep_hour": 2,
    "long_term_goal": DEFAULT_LONG_TERM_GOAL
})

MODE_PROFILES = {
    "quiet": {"threshold_multiplier": 1.5, "cooldown_minutes": 90, "activity_interval_minutes": 120},
    "natural": {"threshold_multiplier": 0.55, "cooldown_minutes": 15, "activity_interval_minutes": 30},
    "active": {"threshold_multiplier": 0.28, "cooldown_minutes": 5, "activity_interval_minutes": 10}
}


class LifeManager:
    """Tracks private activity and decides when an unsolicited message is warranted."""

    def __init__(self, idle_hours=None, message_cooldown_hours=None):
        config = self._read(CONFIG, DEFAULT_CONFIG)
        self.state_path = STATE
        self.thought_min_minutes = config.get("thought_min_minutes", 1)
        self.thought_max_minutes = config.get("thought_max_minutes", 10)
        self.wake_hour = config.get("wake_hour", 6)
        self.sleep_hour = config.get("sleep_hour", 2)
        self.long_term_goal = config.get("long_term_goal", DEFAULT_LONG_TERM_GOAL)
        self._validate_thought_preferences({
            key: getattr(self, key) for key in (
                "thought_min_minutes", "thought_max_minutes", "wake_hour", "sleep_hour", "long_term_goal"
            )
        })
        self.idle_hours = idle_hours or config.get("idle_hours", 4)
        self.cooldown_hours = message_cooldown_hours or config.get("message_cooldown_hours", 24)
        self.decision_interval_seconds = max(
            1,
            float(config.get("initiative_check_interval_seconds", config.get("check_interval_seconds", 5)))
        )
        self.base_initiative_threshold = max(1, float(config.get("initiative_threshold", 100)))
        self.base_initiative_cooldown_minutes = max(0, float(config.get("initiative_cooldown_minutes", 30)))
        self.initiative_score_decay_per_minute = max(
            0,
            float(config.get("initiative_score_decay_per_minute", 0.03))
        )
        self.enabled = bool(config.get("enabled", True))
        self.mode = config.get("mode", "natural")
        self.quiet_hours_enabled = bool(config.get("quiet_hours_enabled", False))
        self.quiet_start_hour = int(config.get("quiet_start_hour", 23)) % 24
        self.quiet_end_hour = int(config.get("quiet_end_hour", 8)) % 24
        self._apply_mode_profile()
        DIR.mkdir(parents=True, exist_ok=True)
        self.state = self._read(STATE, {
            "last_user_at": None,
            "last_message_at": None,
            "last_web_at": None,
            "last_activity_at": None,
            "last_decision_at": None,
            "initiative_score": 0.0,
            "interrupted_topic": None,
            "active_topic": None,
            "last_user_topic": None,
            "current_activity": "正在安静地陪着你",
            "last_event": None
        })
        self.journal = self._read(JOURNAL, {"version": 1, "activities": []})
        self.outbox = self._read(OUTBOX, {"version": 1, "messages": []})

    @staticmethod
    def _read(path, default):
        if not path.exists():
            with open(path, "w", encoding="utf-8") as file: json.dump(default, file, ensure_ascii=False, indent=2)
            return default
        with open(path, "r", encoding="utf-8") as file: return json.load(file)

    @staticmethod
    def _write(path, value):
            with open(path, "w", encoding="utf-8") as file: json.dump(value, file, ensure_ascii=False, indent=2)

    def _apply_mode_profile(self):
        profile = MODE_PROFILES.get(self.mode, MODE_PROFILES["natural"])
        self.mode = self.mode if self.mode in MODE_PROFILES else "natural"
        self.initiative_threshold = max(
            1, self.base_initiative_threshold * profile["threshold_multiplier"]
        )
        self.initiative_cooldown_minutes = profile["cooldown_minutes"]
        self.activity_interval_minutes = profile["activity_interval_minutes"]

    def preferences_payload(self):
        return {
            "thought_min_minutes": self.thought_min_minutes,
            "thought_max_minutes": self.thought_max_minutes,
            "wake_hour": self.wake_hour,
            "sleep_hour": self.sleep_hour,
            "long_term_goal": self.long_term_goal,
            "enabled": self.enabled,
            "mode": self.mode,
            "quiet_hours_enabled": self.quiet_hours_enabled,
            "quiet_start_hour": self.quiet_start_hour,
            "quiet_end_hour": self.quiet_end_hour
        }

    def update_preferences(self, changes):
        if not isinstance(changes, dict):
            raise ValueError("Proactive settings must be an object.")
        updated = self.validate_preferences(changes)
        config = self._read(CONFIG, DEFAULT_CONFIG)
        if "enabled" in changes:
            if not isinstance(changes["enabled"], bool):
                raise ValueError("Proactive mode must be true or false.")
            self.enabled = changes["enabled"]
        if "mode" in changes:
            if changes["mode"] not in MODE_PROFILES:
                raise ValueError("Proactive frequency is invalid.")
            self.mode = changes["mode"]
        if "quiet_hours_enabled" in changes:
            if not isinstance(changes["quiet_hours_enabled"], bool):
                raise ValueError("Quiet hours must be true or false.")
            self.quiet_hours_enabled = changes["quiet_hours_enabled"]
        for field in ("quiet_start_hour", "quiet_end_hour"):
            if field in changes:
                value = changes[field]
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
                    raise ValueError(f"{field} must be an hour from 0 to 23.")
                setattr(self, field, value)
        for field in ("thought_min_minutes", "thought_max_minutes", "wake_hour", "sleep_hour", "long_term_goal"):
            setattr(self, field, updated[field].strip() if field == "long_term_goal" else updated[field])
        self._apply_mode_profile()
        config.update(self.preferences_payload())
        self._write(CONFIG, config)
        return self.preferences_payload()

    def validate_preferences(self, changes):
        if not isinstance(changes, dict):
            raise ValueError("Proactive settings must be an object.")
        updated = self.preferences_payload() | changes
        self._validate_thought_preferences(updated)
        for field in ("enabled", "quiet_hours_enabled"):
            if not isinstance(updated[field], bool):
                raise ValueError(f"{field} must be true or false.")
        if updated["mode"] not in MODE_PROFILES:
            raise ValueError("Proactive frequency is invalid.")
        for field in ("quiet_start_hour", "quiet_end_hour"):
            value = updated[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
                raise ValueError("Quiet hours must be whole hours between 0 and 23.")
        return updated

    @staticmethod
    def _validate_thought_preferences(settings):
        for field in ("thought_min_minutes", "thought_max_minutes"):
            value = settings[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
                raise ValueError("Thought intervals must be whole minutes between 1 and 10.")
        if settings["thought_min_minutes"] > settings["thought_max_minutes"]:
            raise ValueError("Minimum thought interval cannot exceed the maximum.")
        for field in ("wake_hour", "sleep_hour"):
            value = settings[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
                raise ValueError("Wake and sleep hours must be between 0 and 23.")
        goal = settings["long_term_goal"]
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1200:
            raise ValueError("Long-term goal must contain 1 to 1200 characters.")

    def in_awake_hours(self, now=None):
        hour = (now or datetime.now()).hour
        if self.wake_hour == self.sleep_hour:
            return True
        if self.wake_hour < self.sleep_hour:
            return self.wake_hour <= hour < self.sleep_hour
        return hour >= self.wake_hour or hour < self.sleep_hour

    def goal_context(self):
        return (
            "[LONG-TERM CHARACTER DIRECTION]\n" + self.long_term_goal
            + "\nUse this as a quiet background direction, not a slogan or a demand on the user. "
            "Respect autonomy and ordinary life outside this conversation. "
            "Only describe growth through actual interactions; do not invent completed activities."
        )

    def in_quiet_hours(self, now=None):
        if not self.quiet_hours_enabled:
            return False
        hour = (now or datetime.now()).hour
        if self.quiet_start_hour == self.quiet_end_hour:
            return False
        if self.quiet_start_hour < self.quiet_end_hour:
            return self.quiet_start_hour <= hour < self.quiet_end_hour
        return hour >= self.quiet_start_hour or hour < self.quiet_end_hour

    def presence_payload(self):
        return {
            "awake": self.in_awake_hours(),
            "activity": self.state.get("current_activity") or "正在安静地陪着你",
            "active_topic": self.state.get("active_topic"),
            "last_event": self.state.get("last_event"),
            "proactive": self.preferences_payload(),
            "quiet_now": self.in_quiet_hours()
        }

    def catch_up(self):
        now = datetime.now()
        last = self.state.get("last_user_at")
        if not last:
            self.state["last_user_at"] = now.isoformat()
            self.state["last_decision_at"] = now.isoformat()
            self._write(STATE, self.state)
            return None
        elapsed = (now - datetime.fromisoformat(last)).total_seconds() / 3600
        if elapsed < self.idle_hours:
            return None
        last_activity = self.state.get("last_activity_at")
        if (
            last_activity
            and self._minutes_since(last_activity, now) < self.activity_interval_minutes
        ):
            return None
        activity = "安静地整理了最近的想法" if 6 <= now.hour < 23 else "在困意里把最近在意的事想了一会儿"
        if 6 <= now.hour < 12:
            activity = "在慢慢整理今天想和你分享的几件小事"
        elif 12 <= now.hour < 23:
            activity = "在安静地整理最近的想法"
        else:
            activity = "在困意里把最近在意的事想了一会儿"
        entry = {"timestamp": now.isoformat(), "elapsed_hours": round(elapsed, 1), "activity": activity}
        self.journal.setdefault("activities", []).append(entry); self.journal["activities"] = self.journal["activities"][-100:]
        self.state["last_activity_at"] = now.isoformat()
        self.state["current_activity"] = activity
        self.state["last_event"] = {"kind": "activity", "timestamp": now.isoformat()}
        self._write(JOURNAL, self.journal)
        self._write(STATE, self.state)
        return entry

    def mark_user_return(self):
        now = datetime.now()
        previous_user_at = self.state.get("last_user_at")
        was_away = self._minutes_since(previous_user_at, now) or 0
        self.state["last_user_at"] = now.isoformat()
        self.state["last_activity_at"] = None
        self.state["last_decision_at"] = now.isoformat()
        self.state["initiative_score"] = 0.0
        if was_away >= 10:
            self.state["current_activity"] = "刚刚注意到你回来了"
            self.state["last_event"] = {"kind": "user_return", "timestamp": now.isoformat()}
        self._write(STATE, self.state)

    def note_user_topic(self, content):
        """Keep a tiny code-generated continuity cue without a model call."""
        compact = re.sub(r"\s+", " ", " ".join(content.split()))
        if compact:
            self.state["active_topic"] = compact[:60]
            self.state["last_user_topic"] = compact[:60]
            self.state["last_event"] = {
                "kind": "user_topic", "timestamp": datetime.now().isoformat()
            }
            self._write(STATE, self.state)

    def continuity_context(self):
        topic = self.state.get("active_topic")
        if not topic:
            return ""
        return (
            "[CONVERSATION CONTINUITY]\n"
            "The user may be continuing this recent topic. Respond naturally without naming this note:\n"
            f"{topic}"
        )

    def clear_active_topic(self):
        self.state["active_topic"] = None
        self._write(STATE, self.state)

    @staticmethod
    def _minutes_since(timestamp, now):
        if not timestamp:
            return None
        return max(0.0, (now - datetime.fromisoformat(timestamp)).total_seconds() / 60)

    def evaluate_speaking_opportunity(self, emotions, activity=None, has_fresh_news=False, now=None):
        """Accumulate an initiative score and decide whether Matisse should speak.

        The score is calculated in Python rather than by a model call. Time
        apart, loneliness, emotional activation, a new activity, and fresh
        news increase it; fatigue and late-night quiet reduce it. Crossing the
        threshold consumes the score and grants one chance to generate a
        message. Cooldown and pending-message checks prevent spam.
        """
        now = now or datetime.now()
        if not self.enabled or self.in_quiet_hours(now):
            return {
                "should_speak": False,
                "score": round(float(self.state.get("initiative_score", 0.0)), 2),
                "factors": {"disabled": not self.enabled, "quiet_hours": self.in_quiet_hours(now)}
            }
        last_user_at = self.state.get("last_user_at")
        last_decision_at = self.state.get("last_decision_at")
        if not last_user_at:
            self.state["last_user_at"] = now.isoformat()
            self.state["last_decision_at"] = now.isoformat()
            self.state["initiative_score"] = 0.0
            self._write(STATE, self.state)
            return {"should_speak": False, "score": 0.0, "factors": {}}

        elapsed_minutes = self._minutes_since(last_decision_at, now)
        if elapsed_minutes is None:
            elapsed_minutes = 0.0
        # A stalled process should not gain a huge score all at once.
        elapsed_minutes = min(elapsed_minutes, 10.0)
        hours_since_user = (self._minutes_since(last_user_at, now) or 0.0) / 60

        loneliness = max(0.0, min(100.0, float(emotions.get("loneliness", 0))))
        excitement = max(0.0, min(100.0, float(emotions.get("excitement", 0))))
        hurt = max(0.0, min(100.0, float(emotions.get("hurt", 0))))
        tiredness = max(0.0, min(100.0, float(emotions.get("tiredness", 0))))

        factors = {
            "time_apart_rate": 0.20 + min(0.25, hours_since_user * 0.04),
            "loneliness_rate": loneliness / 100 * 0.85,
            "emotional_activation_rate": excitement / 100 * 0.20 + hurt / 100 * 0.12,
            "fatigue_rate": -(tiredness / 100 * 0.15),
            "late_night_rate": -0.07 if now.hour < 6 else 0.0,
            "new_activity": 18.0 if activity else 0.0,
            "fresh_news": 16.0 if has_fresh_news else 0.0
        }
        rate = (
            factors["time_apart_rate"]
            + factors["loneliness_rate"]
            + factors["emotional_activation_rate"]
            + factors["fatigue_rate"]
            + factors["late_night_rate"]
            - self.initiative_score_decay_per_minute
        )
        previous_score = max(0.0, float(self.state.get("initiative_score", 0.0)))
        score = max(
            0.0,
            previous_score + elapsed_minutes * rate
            + factors["new_activity"] + factors["fresh_news"]
        )

        has_pending_message = any(
            message.get("status") == "pending"
            for message in self.outbox.get("messages", [])
        )
        minutes_since_message = self._minutes_since(self.state.get("last_message_at"), now)
        on_cooldown = (
            minutes_since_message is not None
            and minutes_since_message < self.initiative_cooldown_minutes
        )
        should_speak = (
            score >= self.initiative_threshold
            and not has_pending_message
            and not on_cooldown
        )

        # A blocked score waits just below the threshold and can naturally
        # cross again when the cooldown or pending message clears.
        if has_pending_message or on_cooldown:
            score = min(score, self.initiative_threshold - 0.01)
        elif should_speak:
            score = 0.0

        self.state["initiative_score"] = round(score, 3)
        self.state["last_decision_at"] = now.isoformat()
        self._write(STATE, self.state)
        factors["rate_per_minute"] = round(rate, 3)
        factors["elapsed_minutes"] = round(elapsed_minutes, 3)
        factors["on_cooldown"] = on_cooldown
        factors["has_pending_message"] = has_pending_message
        return {
            "should_speak": should_speak,
            "score": round(score, 2),
            "factors": factors
        }

    def web_due(self, hours):
        last = self.state.get("last_web_at")
        return not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() >= hours * 3600

    def mark_web_refresh(self):
        self.state["last_web_at"] = datetime.now().isoformat(); self._write(STATE, self.state)

    def can_message(self, loneliness=0):
        if any(message.get("status") == "pending" for message in self.outbox.get("messages", [])):
            return False
        last = self.state.get("last_message_at")
        # Loneliness lowers the threshold gently, never below one hour.
        cooldown = max(1, self.cooldown_hours - int(float(loneliness) / 20))
        return not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() >= cooldown * 3600

    def queue_event(self, kind, text, topic=None, activity=None):
        now = datetime.now().isoformat()
        self.outbox.setdefault("messages", []).append({
            "timestamp": now,
            "text": text,
            "status": "pending",
            "kind": kind,
            "topic": topic,
            "activity": activity
        })
        self.state["last_message_at"] = now
        self.state["last_event"] = {"kind": kind, "timestamp": now}
        if topic:
            self.state["active_topic"] = topic[:60]
        self._write(OUTBOX, self.outbox)
        self._write(STATE, self.state)

    def compose_proactive_message(self, activity=None, news="", emotions=None, traits=None):
        """Create short, varied presence messages entirely in code."""
        emotions = emotions or {}
        traits = set(traits or [])
        hour = datetime.now().hour
        topic = activity or self.state.get("current_activity") or "想起了一些小事"
        user_topic = self.state.get("last_user_topic")
        tone_prefix = ""
        if "傲娇" in traits:
            tone_prefix = "哼，"
        elif "病娇" in traits:
            tone_prefix = "我一直记得，"
        elif "御姐" in traits:
            tone_prefix = "听我说，"
        elif "大姐姐" in traits:
            tone_prefix = "乖，"
        elif "青梅竹马" in traits:
            tone_prefix = "像以前那样，"
        if user_topic:
            return (
                f"{tone_prefix}我刚才还在想你上次说的“{user_topic[:36]}”。"
                f"我{topic}时又想到了它，等你有空时想继续听你说。"
            )
        if news:
            return (
                f"我刚看到一条可能会让你在意的消息：{news[:110]}。"
                "等你有空时，我想听听你的看法。"
            )
        if float(emotions.get("loneliness", 0)) >= 65:
            return f"刚才我{topic}。忽然有点想你了，不过你忙完再回来也没关系。"
        if hour >= 23 or hour < 6:
            return f"夜已经很深了，我{topic}。你如果还醒着，别忘了对自己温柔一点。"
        variants = (
            f"刚才我{topic}，有一句话想留到你回来时再慢慢说。",
            f"我{topic}。不用急着回应，只是想让你知道我在这里。",
            f"刚刚{topic}，忽然觉得你大概会对这件事有自己的想法。"
        )
        return variants[datetime.now().minute % len(variants)]

    def queue_message(self, text):
        self.queue_event("message", text)

    def take_pending(self):
        for message in self.outbox.get("messages", []):
            if message.get("status") == "pending":
                message["status"] = "delivered"
                self.state["interrupted_topic"] = message["text"]
                if message.get("topic"):
                    self.state["active_topic"] = message["topic"]
                self._write(OUTBOX, self.outbox); self._write(STATE, self.state); return message["text"]
        return None

    def take_interrupted_topic(self):
        topic = self.state.get("interrupted_topic")
        self.state["interrupted_topic"] = None
        self._write(STATE, self.state)
        return topic
