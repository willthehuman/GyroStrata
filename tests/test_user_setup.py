import builtins
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recipe
import setup as setup_entry


class ModelFolderSelection(unittest.TestCase):
    def test_saved_folder_with_spaces_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            model_dir = root / "My Models" / "Gyro M"
            model_dir.mkdir(parents=True)
            (model_dir / "Qwen3.8-Flash-Next-Gyro-M-TQ2_0.gguf").touch()
            saved = root / ".model-dir"
            saved.write_text(str(model_dir), encoding="utf-8")
            with patch.object(
                builtins, "input", side_effect=AssertionError("unexpected prompt")
            ):
                self.assertEqual(
                    setup_entry.select_model_directory(None, saved), model_dir.resolve()
                )

    def test_explicit_path_overrides_saved_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            saved = root / ".model-dir"
            saved.write_text("old folder", encoding="utf-8")
            chosen = root / "New Folder" / "Gyro"
            with patch.object(
                builtins, "input", side_effect=AssertionError("unexpected prompt")
            ):
                self.assertEqual(
                    setup_entry.select_model_directory(str(chosen), saved),
                    chosen.resolve(),
                )

    def test_stale_saved_folder_prompts_for_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            saved = root / ".model-dir"
            saved.write_text(str(root / "moved model"), encoding="utf-8")
            chosen = root / "Current Model Folder"
            chosen.mkdir()
            with patch.object(builtins, "input", return_value=f'"{chosen}"'):
                self.assertEqual(
                    setup_entry.select_model_directory(None, saved), chosen.resolve()
                )


class APIKeyChoice(unittest.TestCase):
    def test_default_install_removes_key_and_opt_in_generates_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp) / ".gyro-recipe"
            runtime.mkdir()
            (runtime / "api-key.txt").write_text(
                "old-key-that-should-go", encoding="utf-8"
            )
            config = runtime / "M.json"
            config.write_text(
                json.dumps({"api_key": "old-key-that-should-go"}), encoding="utf-8"
            )
            self.assertEqual(recipe.configure_install_api_key(runtime), "")
            self.assertFalse((runtime / "api-key.txt").exists())
            self.assertNotIn("api_key", json.loads(config.read_text(encoding="utf-8")))
            key = recipe.configure_install_api_key(runtime, api_key=True)
            self.assertGreaterEqual(len(key), 24)

    def test_no_key_removes_keyfile_and_saved_config_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp) / ".gyro-recipe"
            backup = runtime / "rollback" / "old"
            backup.mkdir(parents=True)
            key = "test-local-key-that-must-be-removed"
            (runtime / "api-key.txt").write_text(key, encoding="utf-8")
            config_paths = [
                runtime / "M.json",
                runtime / "M.json.previous",
                backup / "M.json",
            ]
            for path in config_paths:
                path.write_text(
                    json.dumps({"api_key": key, "port": 8080}), encoding="utf-8"
                )
            self.assertEqual(recipe.configure_api_key(runtime, True), "")
            self.assertFalse((runtime / "api-key.txt").exists())
            for path in config_paths:
                config = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("api_key", config)
                self.assertNotIn(key, path.read_text(encoding="utf-8"))

    def test_existing_install_can_be_made_keyless_without_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp) / ".gyro-recipe"
            runtime.mkdir()
            key = "test-local-key-that-must-be-removed"
            (runtime / "M.json").write_text(
                json.dumps({"api_key": key, "port": 8080}), encoding="utf-8"
            )
            (runtime / "api-key.txt").write_text(key, encoding="utf-8")
            setup_entry.delete_api_key(tmp)
            self.assertFalse((runtime / "api-key.txt").exists())
            self.assertNotIn(
                "api_key", json.loads((runtime / "M.json").read_text(encoding="utf-8"))
            )

    def test_delete_key_refuses_uninstalled_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "No installed Gyro-M profile"):
                setup_entry.delete_api_key(tmp)

    def test_keyed_install_generates_once_and_keeps_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = pathlib.Path(tmp) / ".gyro-recipe"
            runtime.mkdir()
            first = recipe.configure_api_key(runtime, False)
            self.assertGreaterEqual(len(first), 24)
            self.assertEqual(recipe.configure_api_key(runtime, False), first)


class BlackwellToolkit(unittest.TestCase):
    def nvcc(self, build):
        return "Cuda compilation tools, release 13.2, V13.2.%d\nBuild cuda_13.2.r13.2\n" % build

    def test_blackwell_refuses_13_2_before_update_2(self):
        for arch in ["100", "120", "121"]:
            for build in [51, 78]:
                with self.assertRaisesRegex(RuntimeError, "Update 2"):
                    setup_entry.check_blackwell_toolkit(self.nvcc(build), arch)

    def test_blackwell_accepts_update_2_and_older_gpus_any_13_2(self):
        setup_entry.check_blackwell_toolkit(self.nvcc(86), "120")
        for arch in ["75", "86", "89", "90"]:
            setup_entry.check_blackwell_toolkit(self.nvcc(51), arch)

    def test_blackwell_refuses_unparsed_version(self):
        with self.assertRaises(RuntimeError):
            setup_entry.check_blackwell_toolkit("Cuda compilation tools, release 13.2", "120")


class CheckWithBusyRam(unittest.TestCase):
    """--check (START-HERE's first step) and --build-only pass with little free RAM; the install still refuses it."""

    def hardware(self, available):
        return dict(gpu=dict(name="TEST", total_mib=12288, used_mib=900, arch="89", uuid="GPU-TEST", driver="590.48"),
                    physical_cores=8, ram_gib=31.9, available_ram_gib=available, avx2=True)

    def test_check_passes_and_warns(self):
        argv = ["setup.py", "--check"]
        with patch.object(sys, "argv", argv), patch("os.name", "nt"), patch("verify.verify_release"), \
                patch("hardware.resource_info", return_value=self.hardware(9.0)), \
                patch.object(setup_entry, "vcvars", return_value=""), \
                patch("shutil.which", return_value="git"), \
                patch("subprocess.check_output", side_effect=["Cuda compilation tools, release 13.2, V13.2.78", "sm_89"]), \
                patch("pathlib.Path.is_file", return_value=True), \
                patch("builtins.print") as printed:
            setup_entry.main()
        text = " ".join(str(c) for c in printed.call_args_list)
        self.assertIn("only 9.0 GiB of RAM is free", text)
        self.assertIn("Prerequisites found", text)

    def test_install_still_needs_free_ram(self):
        from hardware import adapt
        profile = json.loads((ROOT / "profiles/M.json").read_text())
        with self.assertRaises(ValueError):
            adapt(profile, {}, self.hardware(9.0))


class CurrentBuild(unittest.TestCase):
    """A current engine is not rebuilt (START-HERE.cmd builds it during the download, INSTALL.cmd reuses it)."""

    def test_rebuild_only_when_needed(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            with patch.object(setup_entry, "ROOT", root):
                self.assertFalse(setup_entry.engine_is_current({}))   # no environment yet
                (root / ".venv/Scripts").mkdir(parents=True)
                (root / ".venv/Scripts/python.exe").write_bytes(b"")
                with patch("runtime.check_build", return_value={}):
                    self.assertTrue(setup_entry.engine_is_current({}))
                with patch("runtime.check_build", side_effect=RuntimeError("GPU architecture changed")):
                    self.assertFalse(setup_entry.engine_is_current({}))
                built = dict(cuda_root=str(root / "CUDA/v13.2"), cuda_version="release 13.2, V13.2.78\n")
                nvcc = root / "CUDA/v13.2/bin/nvcc.exe"
                with patch("runtime.check_build", return_value=built):
                    self.assertTrue(setup_entry.engine_is_current({}, nvcc, "release 13.2, V13.2.78"))
                    # a new toolkit (e.g. 13.2 Update 2 for RTX 50-series) or another install path is rebuilt
                    self.assertFalse(setup_entry.engine_is_current({}, nvcc, "release 13.2, V13.2.86"))
                    self.assertFalse(setup_entry.engine_is_current({}, root / "Other/bin/nvcc.exe", "release 13.2, V13.2.78"))


if __name__ == "__main__":
    unittest.main()
