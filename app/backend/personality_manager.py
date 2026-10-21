"""Edit the on-disk persona while generation keeps a fixed startup snapshot."""

import hashlib
import os
import uuid
from functools import lru_cache
from pathlib import Path

MAX_PERSONALITY_LENGTH = 16000


class PersonalityConflict(ValueError):
    pass


class PersonalityManager:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        raw = self.path.read_bytes() if self.path.exists() else b""
        return {
            "content": raw.decode("utf-8-sig"),
            "revision": hashlib.sha256(raw).hexdigest(),
            "configured": bool(raw.decode("utf-8-sig").strip()),
        }

    def save(self, content, revision):
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Please write a character personality before saving.")
        if len(content) > MAX_PERSONALITY_LENGTH:
            raise ValueError("Personality must be at most 16000 characters.")
        if not isinstance(revision, str) or revision != self.read()["revision"]:
            raise PersonalityConflict("The personality file changed. Reload it before saving.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Check again so an external edit during writing is not overwritten.
            if revision != self.read()["revision"]:
                raise PersonalityConflict("The personality file changed. Reload it before saving.")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.read()


@lru_cache(maxsize=None)
def startup_personality(path):
    """Load once per backend process; editor saves never invalidate this cache."""
    return PersonalityManager(path).read()
