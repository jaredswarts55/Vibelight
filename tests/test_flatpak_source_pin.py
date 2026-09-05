"""Local Git fixtures for Flatpak source pin validation; no network/builds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_flatpak_manifest.py"
URL = "https://github.com/xenstalker02/Vibelight.git"


class SourcePinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vibelight-pin-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.env = os.environ.copy()
        for name in list(self.env):
            if name.startswith("GIT_"):
                del self.env[name]
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0")
        self.git("init", "-b", "master")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        (self.repo / "scripts").mkdir()
        shutil.copyfile(CHECKER, self.repo / "scripts" / CHECKER.name)
        self.data = {"finish-args": ["--device=dri", "--device=input"],
                     "modules": [{"name": "vibelight", "sources": [
                         {"type": "git", "url": URL, "commit": "0" * 40}]}]}
        self.write_manifest()
        self.commit()
        self.pin = self.git("rev-parse", "HEAD")
        self.data["modules"][0]["sources"][0]["commit"] = self.pin

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def write_manifest(self):
        (self.repo / "vibelight.json").write_text(json.dumps(self.data), encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def check(self):
        return subprocess.run([sys.executable, str(self.repo / "scripts" / CHECKER.name)],
                              env=self.env, text=True, capture_output=True)

    def test_pin_only_commit_allowed(self):
        self.write_manifest()
        self.commit()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pin_at_head_allowed(self):
        self.write_manifest()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_multiple_commits_behind_refused(self):
        self.write_manifest()
        self.commit()
        self.git("commit", "--allow-empty", "-m", "extra")
        self.assertNotEqual(self.check().returncode, 0)

    def test_formatting_only_difference_allowed(self):
        (self.repo / "vibelight.json").write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        self.commit()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_behind_code_change_refused(self):
        self.write_manifest()
        (self.repo / "code.cpp").write_text("new code")
        self.commit()
        self.assertNotEqual(self.check().returncode, 0)

    def test_one_behind_other_manifest_change_refused(self):
        self.data["runtime-version"] = "different-runtime"
        self.write_manifest()
        self.commit()
        self.assertNotEqual(self.check().returncode, 0)

    def test_one_behind_dirty_manifest_change_refused(self):
        self.write_manifest()
        self.commit()
        self.data["runtime-version"] = "uncommitted-runtime"
        self.write_manifest()
        self.assertNotEqual(self.check().returncode, 0)

    def test_non_hex_pin_gets_validation_error(self):
        self.data["modules"][0]["sources"][0]["commit"] = "z" * 40
        self.write_manifest()
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("40-character hexadecimal", result.stderr)


if __name__ == "__main__":
    unittest.main()
