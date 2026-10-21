"""Small, high-priority character facts injected only for matching topics."""

import json
import re

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CANON_FILE = ROOT_DIR / "config" / "character_canon.json"

DEFAULT_CANON = {"version": 1, "entries": []}


class CanonManager:
    def __init__(self):
        self.data = self._load()

    @staticmethod
    def _write(data):
        CANON_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CANON_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _load(self):
        if not CANON_FILE.exists():
            data = json.loads(json.dumps(DEFAULT_CANON, ensure_ascii=False))
            self._write(data)
            return data
        try:
            with open(CANON_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Character canon is invalid: {CANON_FILE}") from error
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise RuntimeError(f"Character canon is invalid: {CANON_FILE}")
        return data

    def context_for(self, user_input):
        normalized = re.sub(r"\s+", " ", user_input).casefold()
        matches = []
        for entry in self.data["entries"]:
            if not isinstance(entry, dict):
                continue
            keywords = entry.get("keywords", [])
            instruction = entry.get("instruction")
            if (
                isinstance(instruction, str)
                and any(isinstance(keyword, str) and keyword.casefold() in normalized for keyword in keywords)
            ):
                matches.append(instruction.strip())
        if not matches:
            return ""
        return "[CHARACTER CANON — HIGHEST PRIORITY]\n" + "\n".join(
            f"- {instruction}" for instruction in matches
        )
