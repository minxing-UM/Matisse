import hashlib
import json
import math
import random
import re
import uuid

from copy import deepcopy

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

try:
    from ollama import embed as ollama_embed
except ImportError:
    ollama_embed = None


ROOT_DIR = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT_DIR / "repository" / "memories"
MEMORIES_FILE = MEMORY_DIR / "memories.json"
QUEUE_FILE = MEMORY_DIR / "memory_queue.json"
EMBEDDINGS_FILE = MEMORY_DIR / "memory_embeddings.json"

DEFAULT_MEMORIES = {"version": 1, "memories": []}
DEFAULT_QUEUE = {"version": 1, "turns": []}
DEFAULT_EMBEDDINGS = {"version": 1, "model": None, "items": {}}
MEMORY_CATEGORIES = ("general", "preference", "profile", "relationship", "goal", "event", "boundary")


class MemoryManager:
    """Keeps private durable memories and unsummarized conversation turns."""

    def __init__(
        self,
        summary_interval=6,
        context_limit=8,
        fatigue_recall_threshold=60,
        fatigue_recall_chance=0.25,
        fatigue_recall_limit=2,
        fatigue_recall_importance_ceiling=2.5,
        embedding_enabled=True,
        embedding_model="bge-m3:latest",
        embedding_top_k=5,
        embedding_min_similarity=0.48
    ):
        if summary_interval < 1 or context_limit < 1:
            raise ValueError("Memory limits must be positive integers.")
        if not 0 <= fatigue_recall_threshold <= 100:
            raise ValueError("Fatigue recall threshold must be between 0 and 100.")
        if not 0 <= fatigue_recall_chance <= 1:
            raise ValueError("Fatigue recall chance must be between 0 and 1.")
        if fatigue_recall_limit < 1:
            raise ValueError("Fatigue recall limit must be a positive integer.")
        if not 0 <= fatigue_recall_importance_ceiling <= 5:
            raise ValueError("Fatigue recall importance ceiling must be between 0 and 5.")
        if embedding_top_k < 1:
            raise ValueError("Embedding top-k must be a positive integer.")
        if not 0 <= embedding_min_similarity <= 1:
            raise ValueError("Embedding similarity threshold must be between 0 and 1.")

        self.summary_interval = summary_interval
        self.context_limit = context_limit
        self.fatigue_recall_threshold = fatigue_recall_threshold
        self.fatigue_recall_chance = fatigue_recall_chance
        self.fatigue_recall_limit = fatigue_recall_limit
        self.fatigue_recall_importance_ceiling = fatigue_recall_importance_ceiling
        self.embedding_enabled = bool(embedding_enabled)
        self.embedding_model = str(embedding_model).strip() or "bge-m3:latest"
        self.embedding_top_k = embedding_top_k
        self.embedding_min_similarity = float(embedding_min_similarity)
        self.last_retrieval = {"mode": "not_run", "selected": []}
        self._random = random.SystemRandom()
        self._recent_fatigue_recall_ids = deque(
            maxlen=max(6, fatigue_recall_limit * 4)
        )
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_files()
        self.data = self._load_json(MEMORIES_FILE)
        self.queue = self._load_json(QUEUE_FILE)
        self.embeddings = self._load_json(EMBEDDINGS_FILE)
        if self.embeddings.get("model") != self.embedding_model:
            self.embeddings = {
                "version": 1,
                "model": self.embedding_model,
                "items": {}
            }
        self.expire_memories()

    @staticmethod
    def _load_json(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid JSON in {path}") from error

        if not isinstance(data, dict):
            raise RuntimeError(f"Expected a JSON object in {path}")
        return data

    @staticmethod
    def _save_json(path, data):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def _ensure_files(self):
        if not MEMORIES_FILE.exists():
            self._save_json(MEMORIES_FILE, DEFAULT_MEMORIES)
        if not QUEUE_FILE.exists():
            self._save_json(QUEUE_FILE, DEFAULT_QUEUE)
        if not EMBEDDINGS_FILE.exists():
            self._save_json(EMBEDDINGS_FILE, DEFAULT_EMBEDDINGS)

    def _save_memories(self):
        self._save_json(MEMORIES_FILE, self.data)

    def _save_queue(self):
        self._save_json(QUEUE_FILE, self.queue)

    def _save_embeddings(self):
        self._save_json(EMBEDDINGS_FILE, self.embeddings)

    @staticmethod
    def _retention_period(importance):
        if importance >= 4.0:
            return None
        if importance <= 0.5:
            return timedelta(hours=24)
        if importance <= 1.0:
            return timedelta(days=3)
        if importance <= 2.0:
            return timedelta(days=14)
        if importance <= 3.0:
            return timedelta(days=60)
        return timedelta(days=180)

    @classmethod
    def _expires_at(cls, importance, timestamp):
        retention = cls._retention_period(importance)
        return None if retention is None else (timestamp + retention).isoformat()

    def expire_memories(self, now=None):
        now = now or datetime.now()
        expired = 0
        for memory in self.data.get("memories", []):
            if memory.get("status", "active") != "active":
                continue
            expires_at = memory.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) <= now:
                memory["status"] = "forgotten"
                memory["forgotten_at"] = now.isoformat()
                expired += 1
        if expired:
            self._save_memories()
        return expired

    def queue_turn(
        self, chat_id, user_content, assistant_content,
        user_message_id=None, assistant_message_id=None
    ):
        self.queue.setdefault("turns", []).append({
            "chat_id": chat_id,
            "user": user_content,
            "assistant": assistant_content,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "timestamp": datetime.now().isoformat()
        })
        self._save_queue()

    def queue_snapshot(self):
        """Take a small in-memory rollback snapshot before a branch edit."""
        return deepcopy(self.queue)

    def restore_queue(self, snapshot):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("turns"), list):
            raise ValueError("Memory queue snapshot is invalid.")
        self.queue = snapshot
        self._save_queue()

    def reconcile_pending_for_chat(self, chat_id, valid_message_ids):
        """Remove only queued turns that belong to a discarded chat branch.

        Older queue rows lack message ids, so they cannot be proven to belong
        to the remaining branch and are conservatively dropped for that chat.
        """
        valid_message_ids = set(valid_message_ids)
        turns = self.queue.get("turns", [])
        kept = []
        for turn in turns:
            if turn.get("chat_id") != chat_id:
                kept.append(turn)
                continue
            user_id = turn.get("user_message_id")
            assistant_id = turn.get("assistant_message_id")
            if user_id in valid_message_ids and assistant_id in valid_message_ids:
                kept.append(turn)
        removed = len(turns) - len(kept)
        if removed:
            self.queue["turns"] = kept
            self._save_queue()
        return removed

    def remap_pending_message_ids(self, chat_id, replacements):
        """Keep queued memory provenance aligned when a reply keeps its id."""
        changed = False
        for turn in self.queue.get("turns", []):
            if turn.get("chat_id") != chat_id:
                continue
            for field in ("user_message_id", "assistant_message_id"):
                original = turn.get(field)
                if original in replacements:
                    turn[field] = replacements[original]
                    changed = True
        if changed:
            self._save_queue()

    def discard_pending_for_chat(self, chat_id):
        """Drop unsummarized turns before a chat is edited or deleted."""
        turns = self.queue.get("turns", [])
        kept = [turn for turn in turns if turn.get("chat_id") != chat_id]
        removed = len(turns) - len(kept)
        if removed:
            self.queue["turns"] = kept
            self._save_queue()
        return removed

    def should_summarize(self):
        return len(self.queue.get("turns", [])) >= self.summary_interval

    def summarize_pending(self, extractor):
        """Keep pending turns on failure and expose the result without private text."""
        if not self.queue.get("turns"):
            return 0
        pending = self.queue_snapshot()
        try:
            summary = extractor(self.get_pending_messages(), self.get_memory_index())
            stored = self.store_summary(summary.memories)
        except Exception:
            self.queue = pending
            self.queue["last_summary"] = {
                "status": "failed", "timestamp": datetime.now().isoformat()
            }
            self._save_queue()
            raise
        self.queue["last_summary"] = {
            "status": "success", "stored": stored, "timestamp": datetime.now().isoformat()
        }
        self._save_queue()
        return stored

    def get_pending_messages(self):
        messages = []
        for turn in self.queue.get("turns", []):
            messages.extend([
                {"role": "user", "content": turn["user"]},
                {"role": "assistant", "content": turn["assistant"]}
            ])
        return messages

    def get_memory_index(self, limit=60):
        active = [
            memory for memory in self.data.get("memories", [])
            if memory.get("status", "active") == "active"
        ]
        return "\n".join(
            f"{memory.get('memory_key', 'legacy.' + memory['id'])}: {memory['content']}"
            for memory in active[-limit:]
        ) or "(none)"

    @staticmethod
    def _public_memory(memory):
        return {
            "id": memory.get("id"),
            "memory_key": memory.get("memory_key", ""),
            "content": memory.get("content", ""),
            "category": memory.get("category", "general"),
            "importance": memory.get("importance"),
            "pinned": bool(memory.get("pinned", False)),
            "status": memory.get("status", "active"),
            "created_at": memory.get("created_at"),
            "updated_at": memory.get("updated_at"),
            "occurrences": memory.get("occurrences", 1)
        }

    def list_memories(self, query="", include_forgotten=False):
        query = " ".join(str(query).casefold().split())
        memories = []
        for memory in self.data.get("memories", []):
            if not include_forgotten and memory.get("status", "active") != "active":
                continue
            searchable = " ".join((
                memory.get("content", ""), memory.get("memory_key", ""),
                memory.get("category", "general")
            )).casefold()
            if query and query not in searchable:
                continue
            memories.append(self._public_memory(memory))
        memories.sort(key=lambda memory: memory.get("updated_at") or "", reverse=True)
        memories.sort(key=lambda memory: (
            not memory["pinned"], memory["status"] != "active"
        ))
        return memories

    @staticmethod
    def _validate_memory_content(content):
        if not isinstance(content, str):
            raise ValueError("Memory content must be text.")
        content = " ".join(content.split()).strip()
        if not content or len(content) > 500:
            raise ValueError("Memory content must be between 1 and 500 characters.")
        return content

    @staticmethod
    def _validate_category(category):
        if category not in MEMORY_CATEGORIES:
            raise ValueError("Memory category is invalid.")
        return category

    @staticmethod
    def _validate_importance(importance):
        if isinstance(importance, bool) or not isinstance(importance, (int, float)):
            raise ValueError("Memory importance must be a number.")
        if not math.isfinite(importance):
            raise ValueError("Memory importance must be a finite number.")
        return round(max(0, min(5, float(importance))), 2)

    def add_manual_memory(self, content, category="general", importance=3):
        now = datetime.now()
        content = self._validate_memory_content(content)
        category = self._validate_category(category)
        importance = self._validate_importance(importance)
        memory = {
            "id": f"memory_{uuid.uuid4().hex[:10]}",
            "memory_key": f"manual.{uuid.uuid4().hex[:12]}",
            "content": content,
            "category": category,
            "importance": importance,
            "pinned": False,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": self._expires_at(importance, now),
            "status": "active",
            "occurrences": 1
        }
        self.data.setdefault("memories", []).append(memory)
        self._save_memories()
        return self._public_memory(memory)

    def update_memory(self, memory_id, changes):
        if not isinstance(changes, dict):
            raise ValueError("Memory changes must be an object.")
        memory = next((item for item in self.data.get("memories", []) if item.get("id") == memory_id), None)
        if memory is None:
            raise ValueError("Memory was not found.")
        if "expected_content" in changes and changes["expected_content"] != memory.get("content"):
            raise ValueError("这条记忆已被更新，请刷新后再整理措辞。")
        if "content" in changes:
            memory["content"] = self._validate_memory_content(changes["content"])
        if "category" in changes:
            memory["category"] = self._validate_category(changes["category"])
        if "importance" in changes:
            memory["importance"] = self._validate_importance(changes["importance"])
            memory["expires_at"] = self._expires_at(memory["importance"], datetime.now())
        if "pinned" in changes:
            if not isinstance(changes["pinned"], bool):
                raise ValueError("Memory pinned must be true or false.")
            memory["pinned"] = changes["pinned"]
        memory["updated_at"] = datetime.now().isoformat()
        self._save_memories()
        return self._public_memory(memory)

    def delete_memory(self, memory_id):
        memories = self.data.get("memories", [])
        index = next((i for i, memory in enumerate(memories) if memory.get("id") == memory_id), None)
        if index is None:
            raise ValueError("Memory was not found.")
        removed = memories.pop(index)
        self._save_memories()
        return self._public_memory(removed)

    @staticmethod
    def _normalized(content):
        return " ".join(content.casefold().split())

    def store_summary(self, candidates):
        now = datetime.now()
        memories = self.data.setdefault("memories", [])
        stored = 0

        for candidate in candidates:
            content = candidate.content.strip()
            if not content:
                continue
            importance = round(max(0.0, min(5.0, float(candidate.importance))), 2)
            memory_key = getattr(candidate, "memory_key", "") or self._normalized(content)
            reinforcement = float(getattr(candidate, "reinforcement", 0))
            existing = next(
                (
                    memory for memory in memories
                    if memory.get("status", "active") == "active"
                    and (
                        memory.get("memory_key") == memory_key
                        or self._normalized(memory.get("content", "")) == self._normalized(content)
                    )
                ),
                None
            )

            if existing:
                # Repetition strengthens gradually; corrections weaken it.
                # The square root prevents a familiar topic from reaching 5 too fast.
                occurrences = existing.get("occurrences", 1)
                direction = reinforcement if reinforcement else 0.35
                delta = round(direction * 0.65 / (occurrences ** 0.5), 2)
                existing["importance"] = round(
                    max(0.0, min(5.0, existing["importance"] + delta)),
                    2
                )
                existing["memory_key"] = memory_key
                if reinforcement < 0:
                    existing["content"] = content
                existing["updated_at"] = now.isoformat()
                existing["occurrences"] = occurrences + 1
                existing["expires_at"] = self._expires_at(existing["importance"], now)
            else:
                memories.append({
                    "id": f"memory_{uuid.uuid4().hex[:10]}",
                    "memory_key": memory_key,
                    "content": content,
                    "importance": importance,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "expires_at": self._expires_at(importance, now),
                    "status": "active",
                    "occurrences": 1
                })
            stored += 1

        self.queue = {"version": 1, "turns": []}
        self._save_memories()
        self._save_queue()
        return stored

    @staticmethod
    def _chinese_characters(text):
        return set(re.findall(r"[\u4e00-\u9fff]", text))

    @staticmethod
    def _embedding_text(memory):
        parts = [
            memory.get("memory_key", ""),
            memory.get("category", "general"),
            memory.get("content", "")
        ]
        return " | ".join(part for part in parts if part)

    @classmethod
    def _embedding_fingerprint(cls, memory):
        return hashlib.sha256(
            cls._embedding_text(memory).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _cosine_similarity(left, right):
        if not left or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def _semantic_relevance(self, active, user_input):
        """Return cross-language similarity scores with an incremental cache."""
        if not self.embedding_enabled or ollama_embed is None or not active:
            return {}

        items = self.embeddings.setdefault("items", {})
        active_ids = {memory.get("id") for memory in active}
        changed = False
        for memory_id in list(items):
            if memory_id not in active_ids:
                del items[memory_id]
                changed = True

        missing = []
        for memory in active:
            memory_id = memory.get("id")
            fingerprint = self._embedding_fingerprint(memory)
            cached = items.get(memory_id, {})
            if (
                cached.get("fingerprint") != fingerprint
                or not isinstance(cached.get("embedding"), list)
            ):
                missing.append((memory, fingerprint))

        try:
            response = ollama_embed(
                model=self.embedding_model,
                input=[user_input] + [self._embedding_text(memory) for memory, _ in missing],
                truncate=True,
                keep_alive="5m"
            )
            vectors = response.embeddings
            if len(vectors) != len(missing) + 1:
                raise RuntimeError("Embedding response length did not match its input.")
            query_vector = vectors[0]
            for (memory, fingerprint), vector in zip(missing, vectors[1:]):
                items[memory["id"]] = {
                    "fingerprint": fingerprint,
                    "embedding": vector
                }
                changed = True
            if changed:
                self.embeddings["model"] = self.embedding_model
                self._save_embeddings()
            scores = {
                memory["id"]: self._cosine_similarity(
                    query_vector,
                    items.get(memory["id"], {}).get("embedding", [])
                )
                for memory in active
            }
            self.last_retrieval = {
                "mode": "semantic",
                "model": self.embedding_model,
                "selected": []
            }
            return scores
        except Exception as error:
            # Chat remains available if Ollama is stopped or the embedding
            # model is missing; lexical retrieval is the safe fallback.
            self.last_retrieval = {
                "mode": "lexical_fallback",
                "error": type(error).__name__,
                "selected": []
            }
            return {}

    def _relevance(self, memory, user_input):
        query_chars = self._chinese_characters(user_input)
        memory_chars = self._chinese_characters(memory.get("content", ""))
        shared_chars = len(query_chars & memory_chars)
        query_words = set(re.findall(r"[a-z0-9_]{2,}", user_input.casefold()))
        memory_words = set(re.findall(r"[a-z0-9_]{2,}", memory.get("content", "").casefold()))
        return shared_chars + 3 * len(query_words & memory_words)

    def build_fatigue_recall_context(self, tiredness, excluded_ids=()):
        """Return a small, occasionally sampled set of sleepy recollections.

        This deliberately samples in code instead of exposing the whole memory
        store to the model. Low-importance memories are used because they are
        more likely to feel like incidental thoughts than defining facts.
        """
        if tiredness < self.fatigue_recall_threshold:
            return ""
        if self._random.random() >= self.fatigue_recall_chance:
            return ""

        excluded_ids = set(excluded_ids)
        candidates = [
            memory for memory in self.data.get("memories", [])
            if memory.get("status", "active") == "active"
            and memory.get("id") not in excluded_ids
            and memory.get("importance", 0) <= self.fatigue_recall_importance_ceiling
        ]
        if not candidates:
            return ""

        unseen = [
            memory for memory in candidates
            if memory.get("id") not in self._recent_fatigue_recall_ids
        ]
        sample_pool = unseen or candidates
        sample_size = self._random.randint(
            1,
            min(self.fatigue_recall_limit, len(sample_pool))
        )
        recalled = self._random.sample(sample_pool, sample_size)
        self._recent_fatigue_recall_ids.extend(
            memory.get("id") for memory in recalled
        )

        items = "\n".join(f"- {memory['content']}" for memory in recalled)
        return f"""
[PRIVATE SPONTANEOUS RECOLLECTIONS]
Matisse is tired, and these are small, unrelated recollections that happened
to drift through her mind. They are optional background, not a checklist. Only
let at most one surface if it genuinely fits the moment; otherwise leave them
unmentioned. Do not say they came from a memory system or force them into an
unrelated reply.
These notes use Matisse's perspective: 我 / I means Matisse,
and 你 / you means the conversation partner.

{items}
""".strip()

    def build_runtime_context(self, user_input, tiredness=None):
        self.expire_memories()
        active = [
            memory for memory in self.data.get("memories", [])
            if memory.get("status", "active") == "active"
        ]
        semantic_scores = self._semantic_relevance(active, user_input)
        semantic_matches = [
            memory_id
            for memory_id, score in sorted(
                semantic_scores.items(), key=lambda item: item[1], reverse=True
            )
            if score >= self.embedding_min_similarity
        ][:self.embedding_top_k]
        semantic_match_ids = set(semantic_matches)
        selected = [
            memory for memory in sorted(
                (
                    memory for memory in active
                    if (
                        memory.get("pinned", False)
                        or memory.get("id") in semantic_match_ids
                        or self._relevance(memory, user_input) > 0
                    )
                ),
                key=lambda memory: (
                    memory.get("pinned", False),
                    semantic_scores.get(memory.get("id"), 0),
                    self._relevance(memory, user_input),
                    memory.get("importance", 0),
                    memory.get("updated_at", "")
                ),
                reverse=True
            )
        ][:self.context_limit]

        if self.last_retrieval.get("mode") != "lexical_fallback":
            self.last_retrieval = {
                "mode": "semantic" if semantic_scores else "lexical",
                "model": self.embedding_model if semantic_scores else None,
                "selected": [
                    {
                        "id": memory.get("id"),
                        "memory_key": memory.get("memory_key"),
                        "similarity": round(
                            semantic_scores.get(memory.get("id"), 0), 4
                        )
                    }
                    for memory in selected
                ]
            }

        contexts = []
        if selected:
            items = "\n".join(f"- {memory['content']}" for memory in selected)
            contexts.append(f"""
[PRIVATE LONG-TERM MEMORY]
These are private, fallible recollections from earlier conversations. Use them
only when relevant. Never mention this memory system, its files, or importance
scores. If a memory directly answers the user's question, answer consistently
from it instead of saying you do not remember. If the user corrects a memory,
follow the user.
The notes are written from Matisse's perspective: 我 / I means Matisse,
and 你 / you means the conversation partner. Keep the participants distinct.

{items}
""".strip())

        if tiredness is not None:
            fatigue_context = self.build_fatigue_recall_context(
                tiredness,
                excluded_ids=(memory.get("id") for memory in selected)
            )
            if fatigue_context:
                contexts.append(fatigue_context)

        return "\n\n".join(contexts)
