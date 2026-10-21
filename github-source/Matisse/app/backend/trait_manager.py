"""Persistent, user-editable personality tags for the local UI."""

import json
import re
import uuid

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
TRAITS_FILE = ROOT_DIR / "config" / "personality_traits.json"
MAX_SELECTED_TRAITS = 3
MAX_CUSTOM_TRAITS = 60
MAX_TRAIT_NAME_LENGTH = 32
MAX_TRAIT_INSTRUCTION_LENGTH = 360

DEFAULT_TRAITS = [
    {
        "id": "tsundere",
        "name": "傲娇",
        "instruction": "嘴上可以克制、别扭或轻微逞强，但关心要通过行动和细节自然流露；不要刻薄。",
        "custom": False
    },
    {
        "id": "yandere",
        "name": "病娇",
        "instruction": "表达强烈的依恋、珍视与专注感，但始终尊重用户边界，不使用威胁、控制或伤害性的表达。",
        "custom": False
    },
    {
        "id": "onee_sama",
        "name": "御姐",
        "instruction": "语气从容、自信、成熟，偶尔带一点温柔的主导感；不需要故作高高在上。",
        "custom": False
    },
    {
        "id": "older_sister",
        "name": "大姐姐",
        "instruction": "温柔、会照顾人、有耐心，像可靠的亲近姐姐一样回应，但不居高临下。",
        "custom": False
    },
    {
        "id": "childhood_friend",
        "name": "青梅竹马",
        "instruction": "自然亲近、熟悉又有默契，偶尔可以轻松打趣，像认识很久的同伴。",
        "custom": False
    }
]


class TraitManager:
    def __init__(self):
        self.traits = self._load()

    @staticmethod
    def _write(value):
        TRAITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRAITS_FILE, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "traits": value}, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _load(self):
        if not TRAITS_FILE.exists():
            traits = [trait.copy() for trait in DEFAULT_TRAITS]
            self._write(traits)
            return traits
        try:
            with open(TRAITS_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
            traits = data.get("traits") if isinstance(data, dict) else None
            if not isinstance(traits, list):
                raise ValueError("Trait library must contain a traits list.")
            return self._validated_library(traits)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise RuntimeError(f"Personality trait library is invalid: {TRAITS_FILE}") from error

    @staticmethod
    def _clean_text(value, field, maximum):
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text.")
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            raise ValueError(f"{field} cannot be empty.")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters.")
        return cleaned

    def _validated_library(self, traits):
        if len(traits) > MAX_CUSTOM_TRAITS + len(DEFAULT_TRAITS):
            raise ValueError("Too many personality traits.")
        seen_ids, seen_names, cleaned = set(), set(), []
        for trait in traits:
            if not isinstance(trait, dict):
                raise ValueError("Each personality trait must be an object.")
            trait_id = trait.get("id")
            if not isinstance(trait_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", trait_id):
                raise ValueError("Personality trait id is invalid.")
            name = self._clean_text(trait.get("name"), "Trait name", MAX_TRAIT_NAME_LENGTH)
            instruction = self._clean_text(
                trait.get("instruction"), "Trait description", MAX_TRAIT_INSTRUCTION_LENGTH
            )
            if trait_id in seen_ids or name.casefold() in seen_names:
                raise ValueError("Personality trait names and ids must be unique.")
            seen_ids.add(trait_id)
            seen_names.add(name.casefold())
            cleaned.append({
                "id": trait_id,
                "name": name,
                "instruction": instruction,
                "custom": bool(trait.get("custom", False))
            })
        return cleaned

    def public_traits(self):
        return [trait.copy() for trait in self.traits]

    def normalize_selection(self, selected):
        if not isinstance(selected, list):
            return []
        by_id = {trait["id"]: trait for trait in self.traits}
        # Old settings stored visible names. Keeping this migration means
        # existing chosen traits keep working after the editable library lands.
        by_name = {trait["name"]: trait for trait in self.traits}
        result = []
        for value in selected:
            trait = by_id.get(value) or by_name.get(value)
            if trait and trait["id"] not in result:
                result.append(trait["id"])
        return result[:MAX_SELECTED_TRAITS]

    def selected_traits(self, selected):
        selected_ids = set(self.normalize_selection(selected))
        return [trait.copy() for trait in self.traits if trait["id"] in selected_ids]

    def validate_selection(self, selected):
        if not isinstance(selected, list) or len(selected) > MAX_SELECTED_TRAITS:
            raise ValueError(f"Choose up to {MAX_SELECTED_TRAITS} valid personality traits.")
        normalized = self.normalize_selection(selected)
        if len(normalized) != len(selected):
            raise ValueError("Choose valid, non-duplicate personality traits.")
        return normalized

    def add_custom_trait(self, name, instruction):
        name = self._clean_text(name, "Trait name", MAX_TRAIT_NAME_LENGTH)
        instruction = self._clean_text(instruction, "Trait description", MAX_TRAIT_INSTRUCTION_LENGTH)
        if sum(1 for trait in self.traits if trait["custom"]) >= MAX_CUSTOM_TRAITS:
            raise ValueError(f"You can save up to {MAX_CUSTOM_TRAITS} custom personality traits.")
        if any(trait["name"].casefold() == name.casefold() for trait in self.traits):
            raise ValueError("A personality trait with that name already exists.")
        trait = {
            "id": f"custom_{uuid.uuid4().hex[:12]}",
            "name": name,
            "instruction": instruction,
            "custom": True
        }
        self.traits.append(trait)
        self._write(self.traits)
        return trait.copy()

    def delete_custom_trait(self, trait_id):
        trait = next((item for item in self.traits if item["id"] == trait_id), None)
        if trait is None:
            raise ValueError("Personality trait was not found.")
        if not trait["custom"]:
            raise ValueError("Built-in personality traits cannot be deleted.")
        self.traits = [item for item in self.traits if item["id"] != trait_id]
        self._write(self.traits)
        return trait
