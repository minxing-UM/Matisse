"""Initialize a fresh installation, create the Ollama model when needed, and run.

Only standard-library imports: usable for --check before dependencies are installed.
Existing user configuration and persona files are never replaced.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def initialize(root):
    config = root / "config"
    config.mkdir(exist_ok=True)
    settings_path = config / "settings.json"
    if not settings_path.exists():
        shutil.copyfile(root / "examples/settings.example.json", settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    if not isinstance(settings, dict) or not isinstance(settings.get("model"), str):
        raise ValueError("config/settings.json must contain a model name.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", settings["model"]):
        raise ValueError("Invalid model name in config/settings.json.")
    persona = config / "personality.md"
    if not persona.exists():
        persona.write_text("", encoding="utf-8")
    # Empty defaults: none of the author's character facts or data are copied.
    for name, data in {
        "character_canon.json": {"version": 1, "entries": []},
        "web_sources.json": {"enabled": False, "sources": []},
        "proactive.json": {"enabled": False},
    }.items():
        if not (config / name).exists():
            write_json(config / name, data)
    modelfile = root / "Modelfile"
    if not modelfile.exists():
        shutil.copyfile(root / "examples/Modelfile.example", modelfile)
    return settings


def find_ollama():
    executable = shutil.which("ollama")
    if executable:
        return executable
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
    if os.name == "nt" and local.is_file():
        return str(local)
    raise RuntimeError("Ollama was not found. Install it from https://ollama.com/download and retry.")


def ollama_url():
    value = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    return value if "://" in value else "http://" + value


def tags():
    with urlopen(ollama_url() + "/api/tags", timeout=3) as response:
        return json.load(response).get("models", [])


def ensure_service(executable, root):
    try:
        tags()
        return
    except (OSError, URLError):
        pass
    # Start only a local service; never silently replace an unreachable remote host.
    from urllib.parse import urlparse
    if urlparse(ollama_url()).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("The configured OLLAMA_HOST is unreachable. Start that server and retry.")
    logs = root / "repository/logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "ollama.log").open("ab") as log:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen([executable, "serve"], stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
    for _ in range(45):
        time.sleep(1)
        try:
            tags()
            return
        except (OSError, URLError):
            pass
    raise RuntimeError("Ollama did not start. Open the Ollama app and retry; see repository/logs/ollama.log.")


def model_exists(models, name):
    canonical = name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"
    return any(model.get("name") in {name, canonical} or model.get("model") in {name, canonical} for model in models)


def run(executable, arguments, root):
    subprocess.run([executable, *arguments], cwd=root, check=True)


def build_model(executable, root, settings, rebuild=False):
    modelfile = root / "Modelfile"
    digest = hashlib.sha256(modelfile.read_bytes()).hexdigest()
    marker = root / "repository/setup/model.json"
    try:
        previous = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        previous = {}
    current = {"model": settings["model"], "modelfile_sha256": digest}
    if rebuild or previous != current or not model_exists(tags(), settings["model"]):
        print("Creating the model from Modelfile (the base model may need downloading)...", flush=True)
        run(executable, ["create", settings["model"], "-f", str(modelfile)], root)
        write_json(marker, current)  # Failed creates never mark the build as complete.
    else:
        print("Modelfile unchanged; using the existing model.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only dependency/service check; no installs, builds or file changes.")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip downloading embeddings on this run; does not change settings.")
    options = parser.parse_args(argv)
    executable = find_ollama()
    if options.check:
        print(f"Python {sys.version.split()[0]}; Ollama: {executable}")
        print(f"Ollama reachable; {len(tags())} local model(s). No changes made.")
        return 0
    settings = initialize(ROOT)
    ensure_service(executable, ROOT)
    build_model(executable, ROOT, settings, rebuild=options.rebuild)
    if settings.get("memory_embedding_enabled", True) and not options.skip_embeddings:
        embedding_model = settings.get("memory_embedding_model", "bge-m3:latest")
        if not isinstance(embedding_model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", embedding_model):
            raise ValueError("Invalid embedding model name.")
        if not model_exists(tags(), embedding_model):
            print("Downloading the embedding model for semantic memory search...", flush=True)
            run(executable, ["pull", embedding_model], ROOT)
    if options.prepare_only:
        print("Setup complete. Run Start.cmd to open Matisse.")
        return 0
    if not (ROOT / "config/personality.md").read_text(encoding="utf-8-sig").strip():
        print("Customize your character in the editor that opens in the browser.", flush=True)
    return subprocess.call([sys.executable, str(ROOT / "app/backend/web_server.py")], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        sys.exit(1)
