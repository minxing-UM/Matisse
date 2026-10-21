"""Exercise setup plans with fake Ollama calls and fresh isolated directories."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
import zipfile

import test_spontaneous_thoughts as fixtures
from scripts import bootstrap, prepare_release


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        directory = fixtures.isolated_directory()
        self.root = directory.__enter__()
        self.addCleanup(directory.__exit__, None, None, None)
        shutil.copytree(bootstrap.ROOT / "examples", self.root / "examples")

    def test_fresh_install_has_no_predefined_persona_or_character_facts(self):
        settings = bootstrap.initialize(self.root)
        self.assertTrue(settings["personality_required"])
        self.assertEqual((self.root / "config/personality.md").read_text(encoding="utf-8"), "")
        self.assertEqual(json.loads((self.root / "config/character_canon.json").read_text())["entries"], [])
        self.assertFalse(json.loads((self.root / "config/proactive.json").read_text())["enabled"])
        self.assertNotIn("SYSTEM", (self.root / "Modelfile").read_text())
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        bootstrap.initialize(self.root)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_existing_persona_config_and_modelfile_are_preserved(self):
        bootstrap.initialize(self.root)
        for name in ("config/personality.md", "Modelfile", "config/character_canon.json"):
            (self.root / name).write_text("private-user-content", encoding="utf-8")
        settings_path = self.root / "config/settings.json"
        settings_path.write_text(json.dumps({"model": "my-model", "temperature": .23}), encoding="utf-8")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(bootstrap.initialize(self.root)["model"], "my-model")
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_model_rebuilds_only_when_changed_missing_or_forced(self):
        settings = bootstrap.initialize(self.root)
        with patch.object(bootstrap, "tags", return_value=[{"name": "matisse-local:latest"}]), patch.object(bootstrap, "run") as run:
            bootstrap.build_model("fake-ollama", self.root, settings)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[1], ["create", "matisse-local", "-f", str(self.root / "Modelfile")])
            bootstrap.build_model("fake-ollama", self.root, settings)
            self.assertEqual(run.call_count, 1)
            with (self.root / "Modelfile").open("a") as file:
                file.write("\nPARAMETER top_p 0.9\n")
            bootstrap.build_model("fake-ollama", self.root, settings)
            self.assertEqual(run.call_count, 2)
            bootstrap.build_model("fake-ollama", self.root, settings, rebuild=True)
            self.assertEqual(run.call_count, 3)
            with patch.object(bootstrap, "tags", return_value=[]):
                bootstrap.build_model("fake-ollama", self.root, settings)
            self.assertEqual(run.call_count, 4)

    def test_failed_create_does_not_mark_model_complete(self):
        settings = bootstrap.initialize(self.root)
        with patch.object(bootstrap, "tags", return_value=[]), patch.object(bootstrap, "run", side_effect=subprocess.CalledProcessError(1, "fake-ollama")):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.build_model("fake-ollama", self.root, settings)
        self.assertFalse((self.root / "repository/setup/model.json").exists())

    def test_embeddings_download_only_if_enabled_and_not_cached(self):
        with patch.object(bootstrap, "ROOT", self.root), patch.object(bootstrap, "find_ollama", return_value="fake-ollama"), patch.object(bootstrap, "ensure_service"), patch.object(bootstrap, "build_model"), patch.object(bootstrap, "tags", return_value=[]), patch.object(bootstrap, "run") as run:
            self.assertEqual(bootstrap.main(["--prepare-only"]), 0)
            self.assertEqual(run.call_args.args[1], ["pull", "bge-m3:latest"])
            run.reset_mock()
            bootstrap.main(["--prepare-only", "--skip-embeddings"])
            run.assert_not_called()
            with patch.object(bootstrap, "tags", return_value=[{"name": "bge-m3:latest"}]):
                bootstrap.main(["--prepare-only"])
            run.assert_not_called()
            settings_path = self.root / "config/settings.json"
            settings = json.loads(settings_path.read_text()); settings["memory_embedding_enabled"] = False
            settings_path.write_text(json.dumps(settings))
            bootstrap.main(["--prepare-only"])
            run.assert_not_called()

    def test_check_is_read_only_and_model_aliases_are_recognized(self):
        with patch.object(bootstrap, "find_ollama", return_value="fake-ollama"), patch.object(bootstrap, "tags", return_value=[]), patch.object(bootstrap, "initialize") as initialize, patch.object(bootstrap, "ensure_service") as serve:
            self.assertEqual(bootstrap.main(["--check"]), 0)
            initialize.assert_not_called(); serve.assert_not_called()
        self.assertTrue(bootstrap.model_exists([{"name": "custom:latest"}], "custom"))
        self.assertFalse(bootstrap.model_exists([{"name": "custom:other"}], "custom"))

    def test_public_archive_uses_only_allowlist_and_refuses_overwrite(self):
        secret = "SYNTHETIC_PRIVATE_" + self.root.name
        for relative in prepare_release.PUBLIC_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # Use the real public source so the archive is also self-contained.
            shutil.copyfile(prepare_release.ROOT / relative, path)
        for relative in ("config/personality.md", "config/settings.json", "Modelfile", "repository/chats/private.json", "private.gguf", "docs/private-note.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(secret)
        target = self.root / "release.zip"
        prepare_release.export(self.root, target)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(set(archive.namelist()), {f"Matisse/{name}" for name in prepare_release.PUBLIC_FILES})
            self.assertFalse(any(secret.encode() in archive.read(name) for name in archive.namelist()))
        with self.assertRaises(FileExistsError):
            prepare_release.export(self.root, target)


if __name__ == "__main__":
    unittest.main()
