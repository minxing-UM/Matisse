import json
import uuid

from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CHAT_DIR = ROOT_DIR / "repository" / "chats"


class ChatManager:

    def __init__(self, model: str = "matisse:latest"):

        CHAT_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now()

        # Prevent a second /new command in the same second from overwriting
        # the chat file created by the first command.
        self.chat_id = (
            f"chat_{now.strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:8]}"
        )
        self.title = "New Chat"

        self.created_at = now.isoformat()
        self.updated_at = self.created_at

        self.model = model
        self.messages = []

        self.file_path = CHAT_DIR / f"{self.chat_id}.json"

        self.save()

    @classmethod
    def load(cls, chat_id: str):
        """Load an existing conversation without creating a new chat file."""
        if not chat_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in chat_id):
            raise ValueError("Invalid chat id.")

        file_path = CHAT_DIR / f"{chat_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Chat was not found: {chat_id}")

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid chat JSON: {file_path}") from error

        if not isinstance(data, dict) or data.get("id") != chat_id:
            raise RuntimeError(f"Invalid chat data: {file_path}")

        chat = cls.__new__(cls)
        chat.chat_id = chat_id
        chat.title = data.get("title") or "New Chat"
        chat.created_at = data.get("created_at") or datetime.now().isoformat()
        chat.updated_at = data.get("updated_at") or chat.created_at
        chat.model = data.get("model") or "matisse:latest"
        chat.messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        chat.file_path = file_path
        return chat

    def add_message(
        self,
        role: str,
        content: str,
        metadata: dict | None = None
    ):

        message = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        if metadata is not None:
            message["metadata"] = metadata

        self.messages.append(message)
        self.updated_at = datetime.now().isoformat()
        self.save()

    def get_messages_for_model(self) -> list[dict]:

        return [
            {
                "role": message["role"],
                "content": message["content"]
            }
            for message in self.messages
            if not message.get("metadata", {}).get("interaction")
        ]

    def save(self):

        data = {
            "id": self.chat_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "messages": self.messages
        }

        temporary = self.file_path.with_suffix(".tmp")
        with open(
            temporary,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )
        temporary.replace(self.file_path)
            
