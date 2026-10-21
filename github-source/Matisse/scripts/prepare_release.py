"""Build a source preview from an explicit allowlist, never from private config.

Run: python scripts/prepare_release.py
The ZIP is a release candidate; review its contents before publishing it.
"""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    ".gitignore", "LICENSE", "README.md", "requirements.txt", "Start.cmd",
    "examples/Modelfile.example", "examples/personality.example.md", "examples/settings.example.json",
    "scripts/Start.ps1", "scripts/bootstrap.py", "scripts/prepare_release.py",
    "docs/emotions.md", "docs/spontaneous-thoughts.md",
    "app/backend/main.py", "app/backend/web_server.py", "app/backend/ollama_client.py",
    "app/backend/chat_manager.py", "app/backend/memory_manager.py", "app/backend/emotion_manager.py",
    "app/backend/life_manager.py", "app/backend/thought_manager.py", "app/backend/generation_queue.py",
    "app/backend/reply_quality.py", "app/backend/demo_mode.py", "app/backend/language.py",
    "app/backend/canon_manager.py", "app/backend/trait_manager.py", "app/backend/web_manager.py",
    "app/backend/personality_manager.py",
    "app/frontend/index.html", "app/frontend/app.js", "app/frontend/app.css",
    "app/frontend/demo.html", "app/frontend/demo.js", "app/frontend/demo.css",
    "app/frontend/i18n.js", "app/frontend/translations.json", "app/frontend/language.css",
    "app/frontend/personality.js",
    "tests/test_spontaneous_thoughts.py", "tests/test_thought_novelty.py", "tests/test_reply_quality.py",
    "tests/test_sadness.py", "tests/test_resonance.py", "tests/test_memory_notes.py",
    "tests/test_demo_mode.py", "tests/test_language.py", "tests/test_personality.py", "tests/test_bootstrap.py",
    "tests/test_frontend_thoughts.cjs", "tests/test_frontend_sadness.cjs", "tests/test_frontend_memories.cjs",
    "tests/test_frontend_demo.cjs", "tests/test_frontend_language.cjs", "tests/test_frontend_personality.cjs",
)


def export(root, target):
    root = Path(root).resolve()
    sources = []
    for relative in PUBLIC_FILES:
        source = root / relative
        source.resolve().relative_to(root)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or linked public file: {relative}")
        sources.append((source, relative))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a fresh path: do not silently replace a previous release.
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, relative in sources:
            archive.write(source, f"Matisse/{relative}")
    return target


if __name__ == "__main__":
    from datetime import datetime
    target = ROOT / "dist" / f"matisse-source-{datetime.now():%Y%m%d-%H%M%S-%f}.zip"
    print(export(ROOT, target))
