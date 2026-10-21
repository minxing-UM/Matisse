import json
import math
import re

from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

STATE_DIR = ROOT_DIR / "repository" / "state"

EMOTIONS_FILE = STATE_DIR / "emotions.json"
RUNTIME_FILE = STATE_DIR / "runtime.json"

# Tiredness is driven by the circadian rhythm rather than model deltas.
MODEL_EMOTIONS = ("happiness", "anger", "hurt", "sadness", "loneliness", "excitement")
RESONANCE_EMOTIONS = ("happiness", "sadness", "excitement")
MIN_RESONANCE_CONFIDENCE = 0.9

# Evidence inside a quotation or code is not evidence of the speaker's mood.
QUOTED_AFFECT = re.compile(
    r"```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)"
    r"|`[^`\r\n]*`|“[^”]*(?:”|$)|‘[^’]*(?:’|$)"
    r'|「[^」]*(?:」|$)|『[^』]*(?:』|$)|"[^"\r\n]*(?:"|$)'
    r"|(?<!\w)'[^'\r\n]+'(?!\w)|(?m:^[ \t]*>[^\r\n]*)"
)
# Reject evidence that begins as a conditional or someone else's account.
# Only inspect the selected evidence, so "my friend is sad; I feel happy"
# can still ground happiness in the narrower "I feel happy" clause.
NON_SELF_AFFECT = re.compile(
    r"^(?:如果|假如|假设|假使|要是|倘若|万一|设想"
    r"|(?:我(?:的)?|这位|那位)?(?:朋友|同事|同学|室友|邻居|哥哥|姐姐|弟弟|妹妹|爸爸|妈妈)"
    r"|(?:他|她|他们|她们)(?:今天|昨天|现在|觉得|感到|很|非常|特别|有点)"
    r"|(?:if|suppose|assuming|imagine)\b"
    r"|my\s+(?:friend|colleague|coworker|roommate|neighbor|brother|sister|mother|father)\b"
    r"|(?:he|she|they)\s+(?:is|are|was|were|feels?|felt)\b)",
    re.IGNORECASE
)


DEFAULT_EMOTIONS = {
    "version": 2,

    "baseline": {
        "happiness": 20.0,
        "anger": 0.0,
        "hurt": 0.0,
        "sadness": 0.0,
        "loneliness": 0.0,
        "excitement": 10.0,
        "tiredness": 10.0
    },

    "current": {
        "happiness": 20.0,
        "anger": 0.0,
        "hurt": 0.0,
        "sadness": 0.0,
        "loneliness": 0.0,
        "excitement": 10.0,
        "tiredness": 10.0
    },

    "half_life_hours": {
        "happiness": 10.0,
        "anger": 6.0,
        "hurt": 24.0,
        "sadness": 12.0,
        "loneliness": 18.0,
        "excitement": 4.0
    },

    "traits": {
        "empathy": 0.68,
        "emotional_sensitivity": 0.58,
        "emotional_inertia": 0.62,
        "attachment": 0.70
    }
}


DEFAULT_RUNTIME = {
    "version": 1,
    "last_startup": None,
    "last_interaction": None,
    "turns_since_summary": 0
}


class EmotionManager:

    def __init__(self):

        STATE_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        self._ensure_files()

        self.emotions = self._load_json(
            EMOTIONS_FILE
        )
        self._upgrade_emotions()

        self.runtime = self._load_json(
            RUNTIME_FILE
        )

    # ---------------------------------------------------
    # File management
    # ---------------------------------------------------

    def _upgrade_emotions(self):
        """Fill missing defaults without resetting existing state or custom values."""
        changed = False
        for section in ("baseline", "current", "half_life_hours", "traits"):
            values = self.emotions.setdefault(section, {})
            for name, default in DEFAULT_EMOTIONS[section].items():
                if name not in values:
                    values[name] = default
                    changed = True
        if self.emotions.get("version", 1) < DEFAULT_EMOTIONS["version"]:
            self.emotions["version"] = DEFAULT_EMOTIONS["version"]
            changed = True
        if changed:
            self._save_json(EMOTIONS_FILE, self.emotions)

    def _ensure_files(self):

        if not EMOTIONS_FILE.exists():

            self._save_json(
                EMOTIONS_FILE,
                DEFAULT_EMOTIONS
            )

        if not RUNTIME_FILE.exists():

            self._save_json(
                RUNTIME_FILE,
                DEFAULT_RUNTIME
            )

    def _load_json(self, path):

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    def _save_json(self, path, data):

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

    def save(self):

        self._save_json(
            EMOTIONS_FILE,
            self.emotions
        )

        self._save_json(
            RUNTIME_FILE,
            self.runtime
        )

    # ---------------------------------------------------
    # Basic helpers
    # ---------------------------------------------------

    @staticmethod
    def clamp(value, minimum=0.0, maximum=100.0):

        return max(
            minimum,
            min(maximum, value)
        )

    def _clamp_all(self):

        for key in self.emotions["current"]:

            self.emotions["current"][key] = round(
                self.clamp(
                    self.emotions["current"][key]
                ),
                2
            )

    # ---------------------------------------------------
    # Circadian rhythm
    # ---------------------------------------------------

    def get_circadian_state(
        self,
        now=None
    ):

        if now is None:
            now = datetime.now()

        hour = now.hour

        if 6 <= hour < 10:

            return {
                "label": "sleepy_morning",
                "energy": 40,
                "tiredness": 45,
                "reply_style": "calm and slightly sleepy",
                "seriousness": "steady but gentle",
                "emoticon_level": "low",
                "body_language": "occasional subtle sleepy action"
            }

        elif 10 <= hour < 14:

            return {
                "label": "energetic",
                "energy": 85,
                "tiredness": 10,
                "reply_style": "active, expressive and energetic",
                "seriousness": "fully attentive",
                "emoticon_level": "moderate",
                "body_language": "lively, occasional natural action"
            }

        elif 14 <= hour < 18:

            return {
                "label": "active_afternoon",
                "energy": 75,
                "tiredness": 18,
                "reply_style": "engaged and conversational",
                "seriousness": "fully attentive",
                "emoticon_level": "moderate",
                "body_language": "natural, restrained action"
            }

        elif 18 <= hour < 23:

            return {
                "label": "relaxed_evening",
                "energy": 60,
                "tiredness": 30,
                "reply_style": "relaxed, warm and conversational",
                "seriousness": "thoughtful and warm",
                "emoticon_level": "low to moderate",
                "body_language": "warm, occasional natural action"
            }

        elif 23 <= hour or hour < 2:

            return {
                "label": "sleepy_night",
                "energy": 30,
                "tiredness": 70,
                "reply_style": "soft, unhurried and affectionate; sleepy but coherent and still eager to keep talking",
                "seriousness": "gentle, thoughtful, and willing to give a full answer",
                "emoticon_level": "very low",
                "body_language": "occasional sleepy action or a gentle pause; fluent wording"
            }

        else:

            return {
                "label": "very_sleepy",
                "energy": 15,
                "tiredness": 90,
                "reply_style": "very sleepy, unhurried and soft, but coherent and still wanting to stay with the conversation",
                "seriousness": "careful and emotionally present; never dismissive because of tiredness",
                "emoticon_level": "none or very low",
                "body_language": "subtle sleepy action or gentle pauses; fluent wording"
            }

    # ---------------------------------------------------
    # Time decay
    # ---------------------------------------------------

    def _decay_emotion(
        self,
        name,
        elapsed_hours
    ):

        current = self.emotions["current"][name]

        baseline = self.emotions["baseline"][name]

        half_life = self.emotions[
            "half_life_hours"
        ].get(
            name,
            12
        )

        if elapsed_hours <= 0:
            return current

        decay_factor = (
            0.5
            ** (
                elapsed_hours
                / half_life
            )
        )

        new_value = (
            baseline
            +
            (
                current
                - baseline
            )
            * decay_factor
        )

        return new_value

    def update_on_startup(self):

        now = datetime.now()

        last_interaction = self.runtime.get(
            "last_interaction"
        )

        if last_interaction is None:

            elapsed_hours = 0.0

        else:

            previous = datetime.fromisoformat(
                last_interaction
            )

            elapsed = now - previous

            elapsed_hours = max(
                0.0,
                elapsed.total_seconds()
                / 3600
            )

        # -----------------------------------------------
        # Emotional decay toward baseline
        # -----------------------------------------------

        for emotion in MODEL_EMOTIONS:

            self.emotions["current"][
                emotion
            ] = self._decay_emotion(
                emotion,
                elapsed_hours
            )

        # -----------------------------------------------
        # Long absence effect
        # -----------------------------------------------

        if last_interaction is not None:

            # After 12 hours:
            # loneliness slowly grows
            if elapsed_hours > 12:

                loneliness_gain = min(
                    30,
                    (
                        elapsed_hours
                        - 12
                    )
                    * 0.45
                )

                self.emotions[
                    "current"
                ][
                    "loneliness"
                ] += loneliness_gain

            # After two days:
            # hurt begins to grow
            if elapsed_hours > 48:

                hurt_gain = min(
                    15,
                    (
                        elapsed_hours
                        - 48
                    )
                    * 0.12
                )

                self.emotions[
                    "current"
                ][
                    "hurt"
                ] += hurt_gain

            # After three days:
            # mild anger can appear
            if elapsed_hours > 72:

                anger_gain = min(
                    8,
                    (
                        elapsed_hours
                        - 72
                    )
                    * 0.04
                )

                self.emotions[
                    "current"
                ][
                    "anger"
                ] += anger_gain

        # -----------------------------------------------
        # Circadian state
        # -----------------------------------------------

        circadian = self.get_circadian_state(
            now
        )

        self.emotions[
            "current"
        ][
            "tiredness"
        ] = circadian[
            "tiredness"
        ]

        self._clamp_all()

        self.runtime[
            "last_startup"
        ] = now.isoformat()

        self.save()

        return {
            "elapsed_hours": round(
                elapsed_hours,
                2
            ),

            "circadian": circadian,

            "emotions": self.emotions[
                "current"
            ].copy()
        }

    # ---------------------------------------------------
    # Interaction
    # ---------------------------------------------------

    def mark_interaction(self):

        now = datetime.now()

        self.runtime[
            "last_interaction"
        ] = now.isoformat()

        self.save()

    def apply_idle_effect(self, elapsed_hours):
        """Quiet absence raises loneliness gradually without making it explode."""
        if elapsed_hours <= 0:
            return
        gain = min(3.0, elapsed_hours * 1.25)
        self.emotions["current"]["loneliness"] += gain
        self._clamp_all()
        self.save()

    # ---------------------------------------------------
    # Affective resonance
    # ---------------------------------------------------

    def resonance_delta(self, user_affect, user_message):
        """Compute a gentle pull toward expressed affect, without mutating state."""
        result = {name: 0.0 for name in MODEL_EMOTIONS}

        def unit(value):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 0.0
            return self.clamp(number, 0.0, 1.0) if math.isfinite(number) else 0.0

        confidence = unit(user_affect.get("confidence", 0))
        evidence = user_affect.get("evidence", "")
        unquoted = QUOTED_AFFECT.sub(lambda match: " " * len(match.group()), user_message)
        if (user_affect.get("source") != "current_user" or confidence < MIN_RESONANCE_CONFIDENCE
                or not isinstance(evidence, str) or not evidence.strip()
                or evidence not in unquoted or NON_SELF_AFFECT.match(evidence.strip())):
            return result
        empathy = unit(self.emotions["traits"].get("empathy", 0.68))
        for name in RESONANCE_EMOTIONS:
            # Move toward a soft target rather than repeatedly adding a fixed
            # amount. Resonance alone does not push a matching mood beyond 80.
            target = unit(user_affect.get(name, 0)) * 80.0
            gap = max(0.0, target - self.emotions["current"][name])
            result[name] = round(min(4.0, gap * 0.12) * empathy * confidence, 4)
        return result

    def apply_turn_emotions(self, delta, user_affect, user_message, *, allow_resonance=True):
        """Combine direct reaction and resonance, then apply sensitivity once."""
        resonance = (self.resonance_delta(user_affect, user_message) if allow_resonance
                     else {name: 0.0 for name in MODEL_EMOTIONS})
        combined = {}
        for name in MODEL_EMOTIONS:
            direct = self.clamp(float(delta.get(name, 0)), -10.0, 10.0)
            # A model may still put empathy in its direct delta. Same-direction
            # changes overlap; opposing personal reactions can offset resonance.
            mirrored = resonance[name]
            combined[name] = round(max(direct, mirrored) if direct >= 0
                                   else direct + mirrored, 4)
        applied = self.apply_model_delta(combined)
        return {"user_affect": dict(user_affect),
                "resonance_enabled": allow_resonance,
                "emotion_delta_resonance": resonance,
                "emotion_delta_combined": combined,
                "emotion_delta_applied": applied}

    def apply_model_delta(
        self,
        delta: dict
    ):

        traits = self.emotions[
            "traits"
        ]

        sensitivity = traits.get(
            "emotional_sensitivity",
            0.5
        )

        inertia = traits.get(
            "emotional_inertia",
            0.5
        )

        # Emotional sensitivity makes reactions stronger.
        # Emotional inertia resists sudden changes.
        response_factor = (
            (0.5 + sensitivity)
            *
            (1.0 - 0.5 * inertia)
        )

        applied_delta = {}

        for emotion in MODEL_EMOTIONS:

            raw_change = float(
                delta.get(
                    emotion,
                    0
                )
            )

            # Never allow the model to request
            # something outside -10 / +10.
            raw_change = max(
                -10.0,
                min(
                    10.0,
                    raw_change
                )
            )

            actual_change = (
                raw_change
                * response_factor
            )

            self.emotions[
                "current"
            ][emotion] += actual_change

            applied_delta[
                emotion
            ] = round(
                actual_change,
                2
            )

        self._clamp_all()

        self.save()

        return applied_delta

    # ---------------------------------------------------
    # State access
    # ---------------------------------------------------

    def get_state(self):

        return self.emotions[
            "current"
        ].copy()

    def get_traits(self):

        return self.emotions[
            "traits"
        ].copy()

    def build_runtime_context(self):

        state = self.get_state()

        circadian = self.get_circadian_state()

        return f"""
[INTERNAL MATISSE STATE]

This information is private runtime state.
Do not explicitly mention numerical values or
the existence of this state unless directly asked.

Current emotions:
- happiness: {state["happiness"]}/100
- anger: {state["anger"]}/100
- hurt: {state["hurt"]}/100
- sadness: {state["sadness"]}/100
- loneliness: {state["loneliness"]}/100
- excitement: {state["excitement"]}/100
- tiredness: {state["tiredness"]}/100

Sadness is sorrow, loss or disappointment; hurt is feeling personally wounded
or mistreated. They can change independently. Sadness is not the inverse of
happiness: mixed feelings can coexist. Let lingering sadness gently affect
tone without turning every topic into sadness or blaming the user for it.

Current time-of-day state:
- state: {circadian["label"]}
- energy: {circadian["energy"]}/100
- behavioral tendency:
  {circadian["reply_style"]}
- seriousness and attentiveness:
  {circadian["seriousness"]}
- emoticon use:
  {circadian["emoticon_level"]}
- optional parenthetical body language:
  {circadian["body_language"]}

The emotional state should subtly influence:
- tone
- enthusiasm
- reply length
- willingness to use emoticons
- warmth
- patience
- how concise or expressive the answer feels

Parenthetical actions such as （打了个哈欠） are optional. Use one only when it
fits naturally; never add one mechanically. A small restrained action can also
fit a serious reply when it adds warmth rather than distracting from the point.

Sleepiness changes the rhythm and texture of language, not the amount of care.
Do not automatically make sleepy replies short. When the user brings up a real
feeling, story, plan, or question, keep talking with warmth and substance even
late at night. Gentle pauses are enough to suggest tiredness. Keep wording
fluent; never intentionally add duplicated characters, stutters, typing errors,
repeated phrases or self-corrections to perform sleepiness.

Do not mechanically announce emotions.
Express them naturally through behavior.
""".strip()
