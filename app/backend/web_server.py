"""Local browser interface for Matisse.

Run with ``python app/backend/web_server.py`` and open the printed local URL.
The server intentionally binds to 127.0.0.1 only: chats and mood data remain
on the same machine as the existing JSON repository.
"""

import argparse
import base64
import binascii
import json
import webbrowser

from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__:
    from .chat_manager import CHAT_DIR, ChatManager
    from .generation_queue import GenerationQueue
    from .thought_manager import ThoughtManager
    from .emotion_manager import EmotionManager
    from .demo_mode import DemoManager
    from .language import reply_language, validate_language
    from .life_manager import LifeManager
    from .main import run_idle_cycle, start_idle_worker
    from .memory_manager import MemoryManager
    from .ollama_client import CONFIG_FILE, PERSONALITY_FILE, INFERENCE_PROFILES, ask_matisse, load_settings, rephrase_memory, summarize_memories
    from .personality_manager import PersonalityConflict, PersonalityManager, startup_personality
    from .trait_manager import TraitManager
    from .web_manager import WebManager
else:
    from chat_manager import CHAT_DIR, ChatManager
    from generation_queue import GenerationQueue
    from thought_manager import ThoughtManager
    from emotion_manager import EmotionManager
    from demo_mode import DemoManager
    from language import reply_language, validate_language
    from life_manager import LifeManager
    from main import run_idle_cycle, start_idle_worker
    from memory_manager import MemoryManager
    from ollama_client import CONFIG_FILE, PERSONALITY_FILE, INFERENCE_PROFILES, ask_matisse, load_settings, rephrase_memory, summarize_memories
    from personality_manager import PersonalityConflict, PersonalityManager, startup_personality
    from trait_manager import TraitManager
    from web_manager import WebManager


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "app" / "frontend"
AVATAR_DIR = ROOT_DIR / "repository" / "assets"
AVATAR_META_FILE = AVATAR_DIR / "portrait.json"
MAX_MESSAGE_LENGTH = 6000
DEFAULT_CONTEXT_LENGTH = 8192
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_MEMORY_SUMMARY_INTERVAL = 6
MEMORY_SUMMARY_MODES = {"automatic", "manual"}
INTERACTION_ACTIONS = (
    {"id": "headpat", "label": "摸摸头", "icon": "✦"},
    {"id": "hug", "label": "抱一下", "icon": "♡"},
    {"id": "coffee", "label": "递咖啡", "icon": "☕"},
    {"id": "music", "label": "一起听歌", "icon": "♫"},
    {"id": "dice", "label": "投骰子", "icon": "⚄"},
    {"id": "guess_mood", "label": "猜心情", "icon": "◌"}
)
INTERACTION_DELTAS = {
    "headpat": {"happiness": 1.6, "loneliness": -0.7},
    "hug": {"happiness": 2.2, "loneliness": -1.6},
    "coffee": {"happiness": 0.8},
    "music": {"happiness": 1.1, "excitement": 1.4},
    "dice": {"excitement": 1.8},
    "guess_mood": {"happiness": 0.7}
}
class MatisseWebApp:
    """Coordinates the existing chat, memory, emotion, and model services."""

    def __init__(self):
        settings = load_settings()
        self.model = settings["model"]
        self.personality_manager = PersonalityManager(PERSONALITY_FILE)
        self._active_personality = startup_personality(PERSONALITY_FILE)
        self.memory_manager = MemoryManager(
            summary_interval=settings.get("memory_summary_interval", 6),
            context_limit=settings.get("memory_context_limit", 8),
            fatigue_recall_threshold=settings.get("fatigue_memory_recall_threshold", 60),
            fatigue_recall_chance=settings.get("fatigue_memory_recall_chance", 0.25),
            fatigue_recall_limit=settings.get("fatigue_memory_recall_limit", 2),
            fatigue_recall_importance_ceiling=settings.get(
                "fatigue_memory_recall_importance_ceiling", 2.5
            ),
            embedding_enabled=settings.get("memory_embedding_enabled", True),
            embedding_model=settings.get("memory_embedding_model", "bge-m3:latest"),
            embedding_top_k=settings.get("memory_embedding_top_k", 5),
            embedding_min_similarity=settings.get(
                "memory_embedding_min_similarity", 0.48
            )
        )
        self.emotion_manager = EmotionManager()
        self.emotion_manager.update_on_startup()
        self.web_manager = WebManager()
        self.life_manager = LifeManager()
        self.trait_manager = TraitManager()
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        self._generation_lock = GenerationQueue()
        self.demo_manager = DemoManager()
        self.thought_manager = ThoughtManager()
        self._active_chat_id = None
        start_idle_worker(
            self.life_manager,
            self.emotion_manager,
            self.web_manager,
            generation_lock=self._generation_lock,
            deliver_to_console=False,
            thought_callback=self._generate_thought
        )

    def _generate_thought(self):
        if not self._active_chat_id:
            return None
        if load_settings().get("personality_required", False) and not self._active_personality["configured"]:
            return None
        try:
            chat = ChatManager.load(self._active_chat_id)
        except FileNotFoundError:
            self._active_chat_id = None
            return None
        return self.thought_manager.generate(
            chat, self.life_manager, self.emotion_manager, self.memory_manager
        )

    def enter_demo(self):
        with self._generation_lock:
            # Pause personal proactive delivery while presenting the demo.
            self._active_chat_id = None
        return {"mode": "demo"}

    def create_demo_chat(self, tier, password=None):
        with self._generation_lock:
            chat = self.demo_manager.create(tier, password)
            self._active_chat_id = None
            return chat

    def send_demo_message(self, chat_id, content):
        with self._generation_lock:
            self._active_chat_id = None
            return self.demo_manager.send_message(chat_id, content, ask_matisse)

    def discard_demo_chat(self, chat_id):
        with self._generation_lock:
            return self.demo_manager.discard(chat_id)

    def language_payload(self):
        return {"language": reply_language(load_settings())}

    def personality_payload(self):
        snapshot = self.personality_manager.read()
        return {
            **snapshot,
            "required": bool(load_settings().get("personality_required", False)),
            "active_configured": self._active_personality["configured"],
            "restart_required": snapshot["revision"] != self._active_personality["revision"],
        }

    def update_personality(self, content, revision):
        with self._generation_lock:
            self.personality_manager.save(content, revision)
            return self.personality_payload()

    def require_personality(self):
        if load_settings().get("personality_required", False) and not self._active_personality["configured"]:
            raise ValueError("Please customize your character personality in Settings, then restart the backend.")

    def set_language(self, language):
        validate_language(language)
        with self._generation_lock:
            settings = load_settings()
            settings["language"] = language
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(settings, file, ensure_ascii=False, indent=2)
                file.write("\n")
        return {"language": language}

    @staticmethod
    def _display_title(data):
        title = (data.get("title") or "").strip()
        if title and title != "New Chat":
            return title
        for message in data.get("messages", []):
            if message.get("role") == "user" and message.get("content", "").strip():
                preview = " ".join(message["content"].split())
                return preview[:34] + ("…" if len(preview) > 34 else "")
        return "New Chat"

    @staticmethod
    def _chat_payload(chat):
        return {
            "id": chat.chat_id,
            "title": MatisseWebApp._display_title({
                "title": chat.title,
                "messages": chat.messages
            }),
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "messages": [
                {
                    "id": message.get("id"),
                    "role": message.get("role"),
                    "content": message.get("content", ""),
                    "timestamp": message.get("timestamp"),
                    "proactive": bool(message.get("metadata", {}).get("proactive")),
                    "interaction": bool(message.get("metadata", {}).get("interaction"))
                }
                for message in chat.messages
                if message.get("role") in {"user", "assistant"}
            ]
        }

    def list_chats(self):
        chats = []
        CHAT_DIR.mkdir(parents=True, exist_ok=True)
        for path in CHAT_DIR.glob("chat_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                    continue
                chats.append({
                    "id": data["id"],
                    "title": self._display_title(data),
                    "updated_at": data.get("updated_at") or data.get("created_at"),
                    "message_count": len(data.get("messages", []))
                })
            except (OSError, json.JSONDecodeError):
                # One damaged old file should not make the history unusable.
                continue
        return sorted(chats, key=lambda chat: chat.get("updated_at") or "", reverse=True)

    def create_chat(self):
        with self._generation_lock:
            chat = ChatManager(model=self.model)
            self._active_chat_id = chat.chat_id
            return self._chat_payload(chat)

    def get_chat(self, chat_id):
        with self._generation_lock:
            chat = ChatManager.load(chat_id)
            self._active_chat_id = chat_id
            return self._chat_payload(chat)

    @staticmethod
    def interaction_actions_payload():
        return list(INTERACTION_ACTIONS)

    def _interaction_reply(self, action_id):
        state = self.emotion_manager.get_state()
        if reply_language(load_settings()) == "en":
            return self._interaction_reply_english(action_id, state)
        traits = {
            trait["name"] for trait in self.trait_manager.selected_traits(
                load_settings().get("personality_traits", [])
            )
        }
        prefix = ""
        if "傲娇" in traits:
            prefix = "哼，"
        elif "病娇" in traits:
            prefix = "我会好好记住这一刻的，"
        elif "御姐" in traits:
            prefix = "乖，"
        elif "大姐姐" in traits:
            prefix = "真会照顾人，"
        elif "青梅竹马" in traits:
            prefix = "就知道你会这样，"

        if action_id == "headpat":
            return f"{prefix}你轻轻摸了摸我的头。我下意识靠近一点，心情像被顺顺地安抚好了。"
        if action_id == "hug":
            return f"{prefix}我接住这个拥抱，也悄悄抱紧了你一下。先这样停一会儿也很好。"
        if action_id == "coffee":
            tired = state.get("tiredness", 0)
            note = "我确实有点困了" if tired >= 55 else "我正好想喝点热的"
            return f"{prefix}你把咖啡递过来时，我愣了一下。{note}，谢谢你替我留意到。"
        if action_id == "music":
            return f"{prefix}那就一起听。把这一小段时间留给旋律和你，等听到喜欢的地方再告诉我。"
        if action_id == "dice":
            roll = (sum(ord(character) for character in datetime.now().isoformat()) % 6) + 1
            return f"{prefix}骰子在桌上转了几圈，停在 {roll}。这次算你{'赢' if roll >= 4 else '差一点'}，要不要给它配一个小小的奖励？"
        mood = max(state, key=state.get) if state else "happiness"
        descriptions = {
            "happiness": "你猜得很接近，我现在其实挺开心的。",
            "anger": "被你看出来一点点，不过我没事，和你说话会慢慢平静下来。",
            "hurt": "你很敏锐。现在只要安静陪我说几句就够了。",
            "sadness": "嗯，现在有一点难过。能和你慢慢说说，我觉得很好。",
            "loneliness": "嗯，有一点想念你。不过你在这里，我就好多了。",
            "excitement": "答对啦，我现在有点期待接下来会发生什么。",
            "tiredness": "被发现了，我确实有一点困。但还想陪你待一会儿。"
        }
        return f"{prefix}{descriptions.get(mood, '你猜猜看，我会给你一点提示。')}"

    def _interaction_reply_english(self, action_id, state):
        traits = {trait["id"] for trait in self.trait_manager.selected_traits(
            load_settings().get("personality_traits", [])
        )}
        prefix = next((text for key, text in (
            ("tsundere", "Hmph, "), ("yandere", "I'll treasure this moment. "),
            ("onee_sama", "Come here, "), ("older_sister", "That's thoughtful of you. "),
            ("childhood_friend", "I knew you'd do that. ")
        ) if key in traits), "")
        if action_id == "headpat":
            return prefix + "I lean a little closer as you gently pat my head. That small gesture leaves me feeling soothed."
        if action_id == "hug":
            return prefix + "I return your hug and hold you a little closer. We can stay like this for a moment."
        if action_id == "coffee":
            note = "I was getting a little sleepy" if state.get("tiredness", 0) >= 55 else "I was just wishing for something warm"
            return prefix + f"You hand me a coffee, and I pause for a moment. {note}; thank you for noticing."
        if action_id == "music":
            return prefix + "Let's listen together. I'll leave this little stretch of time to the melody and you; tell me when we reach your favorite part."
        if action_id == "dice":
            roll = (sum(ord(character) for character in datetime.now().isoformat()) % 6) + 1
            outcome = "you win" if roll >= 4 else "so close"
            return prefix + f"The die rolls across the table and lands on {roll} — {outcome}! Shall we give it a little reward?"
        mood = max(state, key=state.get) if state else "happiness"
        return prefix + {
            "happiness": "You guessed well. I'm feeling rather happy right now.",
            "anger": "You noticed a little of it. I'm all right; talking with you helps me settle down.",
            "hurt": "You're perceptive. A little quiet conversation would be enough for now.",
            "sadness": "Yes, I'm a little sad. It feels good to be able to talk it through with you.",
            "loneliness": "I was missing you a little. Having you here already helps.",
            "excitement": "You got it! I'm a little excited about what comes next.",
            "tiredness": "You caught me — I am a little sleepy, but I'd still like to spend some time with you.",
        }.get(mood, "Take a guess, and I'll give you a little hint.")

    def perform_interaction(self, chat_id, action_id):
        action = next((item for item in INTERACTION_ACTIONS if item["id"] == action_id), None)
        if action is None:
            raise ValueError("Interaction action is invalid.")
        with self._generation_lock:
            self.require_personality()
            chat = ChatManager.load(chat_id)
            reply = self._interaction_reply(action_id)
            chat.add_message(
                role="user",
                content=(f"[Interaction: {dict(headpat='Pat head', hug='Hug', coffee='Offer coffee', music='Listen together', dice='Roll dice', guess_mood='Guess mood')[action_id]}]"
                         if reply_language(load_settings()) == "en" else f"【互动：{action['label']}】"),
                metadata={"interaction": True, "action": action_id}
            )
            applied_delta = self.emotion_manager.apply_model_delta(
                INTERACTION_DELTAS[action_id]
            )
            self.emotion_manager.mark_interaction()
            chat.add_message(
                role="assistant",
                content=reply,
                metadata={
                    "interaction": True,
                    "action": action_id,
                    "emotion_delta_applied": applied_delta,
                    "mood_after": self.emotion_manager.get_state()
                }
            )
            return {
                "chat": self._chat_payload(chat),
                "reply": reply,
                "mood": self.mood()
            }

    def mood(self):
        state = self.emotion_manager.get_state()
        circadian = self.emotion_manager.get_circadian_state()
        return {
            "values": state,
            "time_state": circadian["label"],
            "energy": circadian["energy"],
            "next_thought_at": self.thought_manager.state.get("next_thought_at"),
            "generation": self._generation_lock.snapshot()
        }

    def settings_payload(self):
        """Return the subset of settings that the local UI may change."""
        settings = load_settings()
        mode = settings.get("memory_summary_mode", "automatic")
        if mode not in MEMORY_SUMMARY_MODES:
            mode = "automatic"
        return {
            "language": reply_language(settings),
            "personality_required": bool(settings.get("personality_required", False)),
            "personality_configured": self._active_personality["configured"],
            "context_length": settings.get("context_length", DEFAULT_CONTEXT_LENGTH),
            "max_output_tokens": settings.get(
                "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS
            ),
            "performance_profile": settings.get("performance_profile", "balanced"),
            "thinking_enabled": settings.get("thinking_enabled", False),
            "inference_profiles": INFERENCE_PROFILES,
            "personality_traits": self.trait_manager.normalize_selection(
                settings.get("personality_traits", [])
            ),
            "available_personality_traits": self.trait_manager.public_traits(),
            "memory_enabled": settings.get("memory_enabled", True),
            "memory_embedding_enabled": settings.get("memory_embedding_enabled", True),
            "memory_embedding_model": settings.get("memory_embedding_model", "bge-m3:latest"),
            "memory_summary_mode": mode,
            "memory_summary_interval": settings.get(
                "memory_summary_interval", DEFAULT_MEMORY_SUMMARY_INTERVAL
            ),
            "pending_memory_turns": len(self.memory_manager.queue.get("turns", [])),
            "memory_summary_status": self.memory_manager.queue.get("last_summary", {}),
            "proactive": self.life_manager.preferences_payload()
        }

    @staticmethod
    def _positive_integer(value, field, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be a whole number.")
        if not minimum <= value <= maximum:
            raise ValueError(f"{field} must be between {minimum} and {maximum}.")
        return value

    def update_settings(self, changes):
        with self._generation_lock:
            return self._update_settings(changes)

    def _update_settings(self, changes):
        """Persist safe browser preferences and apply memory changes immediately."""
        if not isinstance(changes, dict):
            raise ValueError("Settings must be an object.")

        settings = load_settings()
        proactive_changes = changes.get("proactive")
        if proactive_changes is not None and not isinstance(proactive_changes, dict):
            raise ValueError("Proactive settings must be an object.")
        if proactive_changes is not None:
            self.life_manager.validate_preferences(proactive_changes)
        profile_name = changes.get("performance_profile")
        is_preset_profile = profile_name in INFERENCE_PROFILES
        if profile_name is not None and profile_name != "custom" and not is_preset_profile:
            raise ValueError("Inference profile is invalid.")
        if is_preset_profile:
            profile = INFERENCE_PROFILES[profile_name]
            settings["performance_profile"] = profile_name
            settings["context_length"] = profile["context_length"]
            settings["max_output_tokens"] = profile["max_output_tokens"]
            settings["thinking_enabled"] = profile["thinking_enabled"]
        elif profile_name == "custom":
            settings["performance_profile"] = "custom"

        if "context_length" in changes and not is_preset_profile:
            settings["context_length"] = self._positive_integer(
                changes["context_length"], "Context limit", 1024, 65536
            )
        if "max_output_tokens" in changes and not is_preset_profile:
            settings["max_output_tokens"] = self._positive_integer(
                changes["max_output_tokens"], "Reply token limit", 64, 8192
            )
        if "thinking_enabled" in changes and not is_preset_profile:
            if not isinstance(changes["thinking_enabled"], bool):
                raise ValueError("Thinking mode must be true or false.")
            settings["thinking_enabled"] = changes["thinking_enabled"]
        if "personality_traits" in changes:
            settings["personality_traits"] = self.trait_manager.validate_selection(
                changes["personality_traits"]
            )
        if "memory_enabled" in changes:
            if not isinstance(changes["memory_enabled"], bool):
                raise ValueError("Memory access must be true or false.")
            settings["memory_enabled"] = changes["memory_enabled"]
        if "memory_embedding_enabled" in changes:
            if not isinstance(changes["memory_embedding_enabled"], bool):
                raise ValueError("Semantic memory search must be true or false.")
            settings["memory_embedding_enabled"] = changes["memory_embedding_enabled"]
        if "memory_summary_mode" in changes:
            mode = changes["memory_summary_mode"]
            if mode not in MEMORY_SUMMARY_MODES:
                raise ValueError("Memory summary mode is invalid.")
            settings["memory_summary_mode"] = mode
        if "memory_summary_interval" in changes:
            settings["memory_summary_interval"] = self._positive_integer(
                changes["memory_summary_interval"], "Memory summary interval", 1, 100
            )

        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
            file.write("\n")

        self.memory_manager.summary_interval = settings.get(
            "memory_summary_interval", DEFAULT_MEMORY_SUMMARY_INTERVAL
        )
        self.memory_manager.embedding_enabled = settings.get(
            "memory_embedding_enabled", True
        )
        if proactive_changes is not None:
            self.life_manager.update_preferences(proactive_changes)
            self.thought_manager.schedule(self.life_manager)
        return self.settings_payload()

    def add_personality_trait(self, name, instruction):
        trait = self.trait_manager.add_custom_trait(name, instruction)
        return {"trait": trait, "settings": self.settings_payload()}

    def delete_personality_trait(self, trait_id):
        self.trait_manager.delete_custom_trait(trait_id)
        settings = load_settings()
        selected = self.trait_manager.normalize_selection(settings.get("personality_traits", []))
        if selected != settings.get("personality_traits", []):
            settings["personality_traits"] = selected
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(settings, file, ensure_ascii=False, indent=2)
                file.write("\n")
        return {"settings": self.settings_payload()}

    def memories_payload(self, query=""):
        return {
            "categories": [
                {"id": "general", "label": "其他"},
                {"id": "preference", "label": "喜好"},
                {"id": "profile", "label": "个人信息"},
                {"id": "relationship", "label": "关系"},
                {"id": "goal", "label": "目标"},
                {"id": "event", "label": "重要事件"},
                {"id": "boundary", "label": "边界与禁忌"}
            ],
            "memories": self.memory_manager.list_memories(query=query),
            "summary_status": self.memory_manager.queue.get("last_summary", {}),
            "pending_turns": len(self.memory_manager.queue.get("turns", [])),
            "semantic_search": {
                "enabled": self.memory_manager.embedding_enabled,
                "model": self.memory_manager.embedding_model,
                "last_retrieval": self.memory_manager.last_retrieval
            }
        }

    def add_memory(self, content, category, importance):
        with self._generation_lock:
            memory = self.memory_manager.add_manual_memory(content, category, importance)
        return {"memory": memory, "memories": self.memories_payload()}

    def update_memory(self, memory_id, changes):
        with self._generation_lock:
            memory = self.memory_manager.update_memory(memory_id, changes)
        return {"memory": memory, "memories": self.memories_payload()}

    def preview_memory_wording(self, memory_id):
        with self._generation_lock:
            memory = next((item for item in self.memory_manager.data.get("memories", []) if item.get("id") == memory_id), None)
            if memory is None:
                raise ValueError("Memory was not found.")
            original = memory["content"]
            return {"original_content": original, "content": rephrase_memory(original)}

    def delete_memory(self, memory_id):
        with self._generation_lock:
            self.memory_manager.delete_memory(memory_id)
        return {"memories": self.memories_payload()}

    def presence(self):
        return self.life_manager.presence_payload() | {
            "generation": self._generation_lock.snapshot(),
            "next_thought_at": self.thought_manager.state.get("next_thought_at")
        }

    @staticmethod
    def _avatar_content_type(extension):
        return {
            "png": "image/png",
            "jpg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif"
        }.get(extension)

    def avatar_payload(self):
        try:
            with open(AVATAR_META_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
            filename = data.get("filename")
            if not isinstance(filename, str) or "/" in filename or "\\" in filename:
                raise ValueError("Invalid portrait metadata.")
            path = AVATAR_DIR / filename
            if not path.is_file() or not self._avatar_content_type(path.suffix.lstrip(".").lower()):
                raise FileNotFoundError
            return {"image_url": f"/uploads/{filename}?v={int(path.stat().st_mtime)}"}
        except (OSError, ValueError, json.JSONDecodeError):
            return {"image_url": None}

    def avatar_file(self, filename):
        payload = self.avatar_payload()
        image_url = payload.get("image_url")
        if not image_url or not image_url.startswith(f"/uploads/{filename}?"):
            return None
        path = AVATAR_DIR / filename
        return path if path.is_file() else None

    def save_avatar(self, data_url):
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            raise ValueError("Portrait must be a PNG, JPG, WebP, or GIF image.")
        try:
            header, encoded = data_url.split(",", 1)
        except ValueError as error:
            raise ValueError("Portrait data is invalid.") from error
        extension = {
            "data:image/png;base64": "png",
            "data:image/jpeg;base64": "jpg",
            "data:image/webp;base64": "webp",
            "data:image/gif;base64": "gif"
        }.get(header.lower())
        if not extension or len(encoded) > 7 * 1024 * 1024:
            raise ValueError("Portrait must be a supported image smaller than 5 MB.")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Portrait image data is invalid.") from error
        if not image or len(image) > 5 * 1024 * 1024:
            raise ValueError("Portrait must be smaller than 5 MB.")

        valid_signature = {
            "png": image.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpg": image.startswith(b"\xff\xd8\xff"),
            "gif": image.startswith((b"GIF87a", b"GIF89a")),
            "webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP"
        }[extension]
        if not valid_signature:
            raise ValueError("Portrait file type does not match its image data.")

        target = AVATAR_DIR / f"portrait.{extension}"
        temporary = AVATAR_DIR / f"portrait-upload.{extension}"
        with open(temporary, "wb") as file:
            file.write(image)
        temporary.replace(target)
        for old_extension in ("png", "jpg", "webp", "gif"):
            old_file = AVATAR_DIR / f"portrait.{old_extension}"
            if old_file != target and old_file.exists():
                old_file.unlink()
        with open(AVATAR_META_FILE, "w", encoding="utf-8") as file:
            json.dump({"filename": target.name}, file, ensure_ascii=False)
        return self.avatar_payload()

    def summarize_pending_memories(self, chat_id):
        """Manually turn queued turns into durable memories and acknowledge it."""
        if load_settings().get("memory_summary_mode", "automatic") != "manual":
            raise ValueError("Switch memory summaries to manual mode before using this action.")
        with self._generation_lock:
            chat = ChatManager.load(chat_id)
            pending_turns = len(self.memory_manager.queue.get("turns", []))
            stored = 0
            if pending_turns:
                stored = self.memory_manager.summarize_pending(summarize_memories)

            if stored:
                confirmation = "嗯，我已经把刚才值得记住的事认真记下来了。"
            elif pending_turns:
                confirmation = "我已经认真整理过刚才的对话了，不过没有发现需要长期记住的新事情。"
            else:
                confirmation = "现在还没有需要我整理和记住的新对话。"

            if reply_language(load_settings()) == "en":
                confirmation = ("I've carefully noted the things worth remembering from our conversation." if stored
                                else "I've reviewed our conversation, but didn't find anything new that needs a lasting memory." if pending_turns
                                else "There aren't any new conversations for me to organize into memories yet.")

            chat.add_message(
                role="assistant",
                content=confirmation,
                metadata={"manual_memory_summary": True, "memories_stored": stored}
            )
            return {
                "chat": self._chat_payload(chat),
                "reply": confirmation,
                "memories_stored": stored,
                "settings": self.settings_payload()
            }

    def claim_proactive_message(self, chat_id):
        """Read an atomic snapshot even while a queued answer is generating."""
        chat = ChatManager.load(chat_id)
        last = chat.messages[-1] if chat.messages else {}
        proactive = last.get("metadata", {}).get("proactive")
        return {
            "message": last.get("content") if proactive else None,
            "chat": self._chat_payload(chat), "mood": self.mood(),
            "generation": self._generation_lock.snapshot()
        }

    def send_message(self, chat_id, content, *, allow_resonance=True):
        """Persist one turn and return its public response data.

        Ollama calls are serialized so simultaneous browser requests cannot
        apply emotion changes or append turns out of order.
        """
        content = content.strip()
        if not content:
            raise ValueError("Message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message must be at most {MAX_MESSAGE_LENGTH} characters.")

        with self._generation_lock:
            self.require_personality()
            chat = ChatManager.load(chat_id)
            self._active_chat_id = chat_id
            is_new_chat = not chat.messages
            title_before_turn = chat.title
            self.life_manager.mark_user_return()
            continuity_context = self.life_manager.continuity_context()
            self.life_manager.note_user_topic(content)
            chat.add_message(role="user", content=content)
            user_message_id = chat.messages[-1]["id"]
            if is_new_chat and chat.title == "New Chat":
                title = " ".join(content.split())
                chat.title = title[:34] + ("…" if len(title) > 34 else "")
                chat.save()

            runtime_context = self.emotion_manager.build_runtime_context()
            runtime_context += "\n\n" + self.life_manager.goal_context()
            if continuity_context:
                runtime_context += "\n\n" + continuity_context
            settings = load_settings()
            if settings.get("memory_enabled", True):
                memory_context = self.memory_manager.build_runtime_context(
                    content,
                    tiredness=self.emotion_manager.get_state()["tiredness"]
                )
                if memory_context:
                    runtime_context += "\n\n" + memory_context

            web_context = self.web_manager.build_runtime_context(content)
            if web_context:
                runtime_context += "\n\n" + web_context

            try:
                turn = ask_matisse(
                    chat.get_messages_for_model(),
                    runtime_context=runtime_context
                )
            except Exception:
                # Do not leave an unanswered user message in the persisted
                # branch if Ollama returns nothing or fails validation.
                if chat.messages and chat.messages[-1].get("id") == user_message_id:
                    chat.messages.pop()
                    chat.title = title_before_turn
                    chat.save()
                raise
            proposed_delta = turn.emotion_delta.model_dump()
            emotion_report = self.emotion_manager.apply_turn_emotions(
                proposed_delta, turn.user_affect.model_dump(), content,
                allow_resonance=allow_resonance
            )
            self.emotion_manager.mark_interaction()
            mood_after = self.emotion_manager.get_state()

            chat.add_message(
                role="assistant",
                content=turn.reply,
                metadata={
                    "mood_label": turn.mood_label,
                    "emotion_delta_proposed": proposed_delta,
                    **emotion_report,
                    "mood_after": mood_after
                }
            )

            self.memory_manager.queue_turn(
                chat.chat_id,
                content,
                turn.reply,
                user_message_id=user_message_id,
                assistant_message_id=chat.messages[-1]["id"]
            )
            if (
                settings.get("memory_summary_mode", "automatic") == "automatic"
                and self.memory_manager.should_summarize()
            ):
                try:
                    self.memory_manager.summarize_pending(summarize_memories)
                except Exception as error:
                    # Memory extraction stays private and must not fail a chat reply.
                    print(f"[Memory summary] {type(error).__name__}; queued turns retained.")

            return {
                "chat": self._chat_payload(chat),
                "reply": chat.messages[-1]["content"],
                "mood": self.mood()
            }

    def edit_and_regenerate(self, chat_id, message_id, content):
        content = content.strip()
        if not content:
            raise ValueError("Message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message must be at most {MAX_MESSAGE_LENGTH} characters.")
        with self._generation_lock:
            chat = ChatManager.load(chat_id)
            index = next(
                (i for i, message in enumerate(chat.messages) if message.get("id") == message_id),
                None
            )
            if index is None or chat.messages[index].get("role") != "user":
                raise ValueError("Only user messages can be edited.")
            original_messages = chat.messages[:]
            original_title = chat.title
            queue_before_edit = self.memory_manager.queue_snapshot()
            chat.messages = chat.messages[:index]
            chat.save()
            self.memory_manager.reconcile_pending_for_chat(
                chat_id, (message.get("id") for message in chat.messages)
            )
            try:
                return self.send_message(chat_id, content)
            except Exception:
                chat.messages = original_messages
                chat.title = original_title
                chat.save()
                self.memory_manager.restore_queue(queue_before_edit)
                raise

    def regenerate_reply(self, chat_id, message_id):
        with self._generation_lock:
            chat = ChatManager.load(chat_id)
            index = next(
                (i for i, message in enumerate(chat.messages) if message.get("id") == message_id),
                None
            )
            if index is None or chat.messages[index].get("role") != "assistant":
                raise ValueError("Only assistant messages can be regenerated.")
            if chat.messages[index].get("metadata", {}).get("proactive"):
                raise ValueError("A self-initiated remark cannot be regenerated as a user reply.")
            user_index = next(
                (i for i in range(index - 1, -1, -1) if chat.messages[i].get("role") == "user"),
                None
            )
            if user_index is None:
                raise ValueError("This reply has no user message to regenerate from.")
            original_messages = chat.messages[:]
            original_title = chat.title
            queue_before_regeneration = self.memory_manager.queue_snapshot()
            original_user = chat.messages[user_index].copy()
            original_reply = chat.messages[index].copy()
            content = original_user.get("content", "")
            chat.messages = chat.messages[:user_index]
            chat.save()
            self.memory_manager.reconcile_pending_for_chat(
                chat_id, (message.get("id") for message in chat.messages)
            )
            try:
                # A replacement reply is not a newly expressed user feeling.
                result = self.send_message(chat_id, content, allow_resonance=False)
            except Exception:
                chat.messages = original_messages
                chat.title = original_title
                chat.save()
                self.memory_manager.restore_queue(queue_before_regeneration)
                raise

            refreshed = ChatManager.load(chat_id)
            replacement_user = refreshed.messages[-2]
            replacement_reply = refreshed.messages[-1]
            generated_user_id = replacement_user["id"]
            generated_reply_id = replacement_reply["id"]
            replacement_user["id"] = original_user["id"]
            replacement_user["timestamp"] = original_user["timestamp"]
            replacement_reply["id"] = original_reply["id"]
            replacement_reply["timestamp"] = original_reply["timestamp"]
            refreshed.save()
            self.memory_manager.remap_pending_message_ids(
                chat_id,
                {
                    generated_user_id: original_user["id"],
                    generated_reply_id: original_reply["id"]
                }
            )
            return {
                "chat": self._chat_payload(refreshed),
                "reply": replacement_reply["content"],
                "mood": result["mood"]
            }

    def delete_chat(self, chat_id):
        with self._generation_lock:
            chat = ChatManager.load(chat_id)
            chat.file_path.unlink()
            self.memory_manager.discard_pending_for_chat(chat_id)
            if self._active_chat_id == chat_id:
                self._active_chat_id = None
        return {"deleted": chat_id}


class MatisseRequestHandler(BaseHTTPRequestHandler):
    app: MatisseWebApp

    STATIC_FILES = {
        "/static/personality.js": ("personality.js", "text/javascript; charset=utf-8"),
        "/": ("index.html", "text/html; charset=utf-8"),
        "/demo": ("demo.html", "text/html; charset=utf-8"),
        "/static/demo.css": ("demo.css", "text/css; charset=utf-8"),
        "/static/demo.js": ("demo.js", "application/javascript; charset=utf-8"),
        "/static/app.css": ("app.css", "text/css; charset=utf-8"),
        "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
        "/static/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
        "/static/translations.json": ("translations.json", "application/json; charset=utf-8"),
        "/static/language.css": ("language.css", "text/css; charset=utf-8"),
    }

    def log_message(self, format, *args):
        # Keep the terminal focused on startup and model errors.
        return

    def _send_json(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_json(self, status, message):
        self._send_json(status, {"error": message})

    def _read_json_body(self, max_length=100_000):
        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length or 0)
        except ValueError as error:
            raise ValueError("Invalid request body.") from error
        if length < 1 or length > max_length:
            raise ValueError("Request body is invalid or too large.")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        return body

    @staticmethod
    def _chat_id_from_path(path):
        parts = path.split("/")
        if len(parts) == 4 and parts[1:3] == ["api", "chats"]:
            return parts[3]
        return None

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path.startswith("/uploads/"):
            filename = path.removeprefix("/uploads/")
            portrait = self.app.avatar_file(filename)
            if not portrait:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Portrait was not found.")
                return
            content_type = self.app._avatar_content_type(portrait.suffix.lstrip(".").lower())
            image = portrait.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(image)
            return
        if path in self.STATIC_FILES:
            filename, content_type = self.STATIC_FILES[path]
            try:
                content = (FRONTEND_DIR / filename).read_bytes()
            except OSError:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Frontend asset was not found.")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/api/language":
            self._send_json(HTTPStatus.OK, self.app.language_payload())
            return
        if path == "/api/personality":
            try:
                self._send_json(HTTPStatus.OK, self.app.personality_payload())
            except (OSError, UnicodeError) as error:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            return
        if path == "/api/chats":
            self._send_json(HTTPStatus.OK, {"chats": self.app.list_chats()})
            return
        if path == "/api/mood":
            self._send_json(HTTPStatus.OK, self.app.mood())
            return
        if path == "/api/settings":
            self._send_json(HTTPStatus.OK, self.app.settings_payload())
            return
        if path == "/api/presence":
            self._send_json(HTTPStatus.OK, self.app.presence())
            return
        if path == "/api/avatar":
            self._send_json(HTTPStatus.OK, self.app.avatar_payload())
            return
        if path == "/api/memories":
            query = parse_qs(parsed_url.query).get("q", [""])[0]
            self._send_json(HTTPStatus.OK, self.app.memories_payload(query=query))
            return

        chat_id = self._chat_id_from_path(path)
        if chat_id is not None:
            try:
                self._send_json(HTTPStatus.OK, self.app.get_chat(chat_id))
            except FileNotFoundError:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Chat was not found.")
            except (ValueError, RuntimeError) as error:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_json_body(
                7 * 1024 * 1024 if path == "/api/avatar" else 100_000
            )
            if path == "/api/language":
                self._send_json(HTTPStatus.OK, self.app.set_language(body.get("language")))
                return
            if path == "/api/personality":
                try:
                    result = self.app.update_personality(body.get("content"), body.get("revision"))
                except PersonalityConflict as error:
                    self._send_error_json(HTTPStatus.CONFLICT, str(error))
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            if path == "/api/demo/enter":
                self._send_json(HTTPStatus.OK, self.app.enter_demo())
                return
            if path == "/api/demo/chats":
                self._send_json(HTTPStatus.CREATED, self.app.create_demo_chat(body.get("tier"), body.get("password")))
                return
            if path == "/api/demo/messages":
                self._send_json(HTTPStatus.OK, self.app.send_demo_message(body.get("chat_id"), body.get("content")))
                return
            if path == "/api/demo/discard":
                self._send_json(HTTPStatus.OK, self.app.discard_demo_chat(body.get("chat_id")))
                return
            if path == "/api/chats":
                self._send_json(HTTPStatus.CREATED, self.app.create_chat())
                return

            if path == "/api/proactive/claim":
                chat_id = body.get("chat_id")
                if not isinstance(chat_id, str):
                    raise ValueError("chat_id must be a string.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.claim_proactive_message(chat_id)
                )
                return

            if path == "/api/settings":
                self._send_json(HTTPStatus.OK, self.app.update_settings(body))
                return

            if path == "/api/personality-traits":
                self._send_json(
                    HTTPStatus.CREATED,
                    self.app.add_personality_trait(body.get("name"), body.get("instruction"))
                )
                return

            if path == "/api/avatar":
                self._send_json(HTTPStatus.OK, self.app.save_avatar(body.get("data_url")))
                return

            if path == "/api/memories":
                self._send_json(
                    HTTPStatus.CREATED,
                    self.app.add_memory(
                        body.get("content"),
                        body.get("category", "general"),
                        body.get("importance", 3)
                    )
                )
                return

            if path == "/api/memories/summarize":
                chat_id = body.get("chat_id")
                if not isinstance(chat_id, str):
                    raise ValueError("chat_id must be a string.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.summarize_pending_memories(chat_id)
                )
                return

            if path.startswith("/api/memories/") and path.endswith("/wording-preview"):
                parts = path.split("/")
                if len(parts) != 5 or not parts[3]:
                    raise ValueError("Invalid memory wording request.")
                self._send_json(HTTPStatus.OK, self.app.preview_memory_wording(parts[3]))
                return

            if path.startswith("/api/memories/"):
                memory_id = path.removeprefix("/api/memories/")
                if not memory_id or "/" in memory_id:
                    raise ValueError("Invalid memory update request.")
                self._send_json(HTTPStatus.OK, self.app.update_memory(memory_id, body))
                return

            if path.startswith("/api/chats/") and path.endswith("/edit"):
                parts = path.split("/")
                if len(parts) != 7 or not isinstance(body.get("content"), str):
                    raise ValueError("Invalid message edit request.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.edit_and_regenerate(parts[3], parts[5], body["content"])
                )
                return

            if path.startswith("/api/chats/") and path.endswith("/regenerate"):
                parts = path.split("/")
                if len(parts) != 7:
                    raise ValueError("Invalid message regeneration request.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.regenerate_reply(parts[3], parts[5])
                )
                return

            if path.startswith("/api/chats/") and path.endswith("/interactions"):
                parts = path.split("/")
                if len(parts) != 5 or not isinstance(body.get("action"), str):
                    raise ValueError("Invalid interaction request.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.perform_interaction(parts[3], body["action"])
                )
                return

            if path.startswith("/api/chats/") and path.endswith("/messages"):
                parts = path.split("/")
                if len(parts) != 5:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")
                    return
                content = body.get("content")
                if not isinstance(content, str):
                    raise ValueError("Message content must be a string.")
                self._send_json(
                    HTTPStatus.OK,
                    self.app.send_message(parts[3], content)
                )
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")
        except PermissionError as error:
            self._send_error_json(HTTPStatus.FORBIDDEN, str(error))
        except FileNotFoundError as error:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(error) if path.startswith("/api/demo/") else "Chat was not found.")
        except ValueError as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            # Detailed model errors stay in the local terminal, not in the UI.
            print(f"[Web UI] {type(error).__name__}: {error}")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Matisse could not reply. Please try again.")

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/memories/"):
            memory_id = path.removeprefix("/api/memories/")
            if not memory_id or "/" in memory_id:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")
                return
            try:
                self._send_json(HTTPStatus.OK, self.app.delete_memory(memory_id))
            except (ValueError, RuntimeError) as error:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            return
        if path.startswith("/api/personality-traits/"):
            trait_id = path.removeprefix("/api/personality-traits/")
            if not trait_id or "/" in trait_id:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")
                return
            try:
                self._send_json(HTTPStatus.OK, self.app.delete_personality_trait(trait_id))
            except (ValueError, RuntimeError) as error:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            return
        chat_id = self._chat_id_from_path(path)
        if chat_id is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Route was not found.")
            return
        try:
            self._send_json(HTTPStatus.OK, self.app.delete_chat(chat_id))
        except FileNotFoundError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Chat was not found.")
        except (ValueError, RuntimeError) as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))


def main():
    parser = argparse.ArgumentParser(description="Run Matisse's local browser UI.")
    parser.add_argument("--port", type=int, default=8787, help="Local port to use (default: 8787).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    app = MatisseWebApp()
    handler = type("BoundMatisseRequestHandler", (MatisseRequestHandler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Matisse Web UI is running at {url}")
    print("Press Ctrl+C to stop it.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMatisse Web UI stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
