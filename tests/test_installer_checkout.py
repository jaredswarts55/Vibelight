"""Exercise the real installer checkout phase using local Git fixtures only.

Run: python -m unittest discover -s tests -p test_installer_checkout.py -v
No Flatpak, device access, user Git configuration, or network is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
BASH = (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))
URL = "https://github.com/xenstalker02/Vibelight.git"


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vibelight-checkout-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.repo = self.home / "vibelight"
        self.remote = self.base / "remote"
        self.env = os.environ.copy()
        for name in list(self.env):
            if name.startswith("GIT_"):
                del self.env[name]
        self.env.update(HOME=self.home.as_posix(), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=(self.base / "gitconfig").as_posix(),
                        GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0")
        self.git(self.base, "config", "--global", "user.name", "Fixture")
        self.git(self.base, "config", "--global", "user.email", "fixture@example.invalid")
        self.git(self.base, "config", "--global", "commit.gpgsign", "false")
        self.git(self.base, "config", "--global", "core.autocrlf", "false")
        self.git(self.base, "config", "--global", "url." + self.remote.as_posix() + ".insteadOf", URL)
        self.git(self.base, "init", "-b", "master", str(self.remote))
        (self.remote / "tracked").write_text("original\n")
        (self.remote / ".gitignore").write_text("private.local\n")
        self.commit(self.remote)
        self.git(self.base, "clone", URL, str(self.repo))

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], env=self.env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def commit(self, repo):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "fixture")

    def run_checkout(self):
        # Stop before the first install operation; execute the actual production
        # source prefix, not a reimplementation or a mocked Git command.
        source = INSTALLER.read_text(encoding="utf-8").split("# Ensure the Flatpak Builder", 1)
        self.assertEqual(len(source), 2, "Checkout/install boundary changed: review test isolation")
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", source[0]],
                              cwd=self.base, env=self.env, text=True, capture_output=True)

    def assert_refused(self):
        before = self.git(self.repo, "rev-parse", "HEAD")
        result = self.run_checkout()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), before)

    def test_tracked_edits_preserved(self):
        (self.repo / "tracked").write_text("my work\n")
        self.assert_refused()
        self.assertEqual((self.repo / "tracked").read_text(), "my work\n")

    def test_staged_edits_preserved(self):
        (self.repo / "tracked").write_text("staged work\n")
        self.git(self.repo, "add", "tracked")
        self.assert_refused()
        self.assertIn("staged work", self.git(self.repo, "show", ":tracked"))

    def test_untracked_preserved(self):
        (self.repo / "new-local").write_text("local")
        self.assert_refused()
        self.assertEqual((self.repo / "new-local").read_text(), "local")

    def test_ignored_preserved(self):
        (self.repo / "private.local").write_text("private fixture")
        self.assert_refused()
        self.assertTrue((self.repo / "private.local").exists())

    def test_local_commit_preserved(self):
        (self.repo / "tracked").write_text("local commit")
        self.commit(self.repo)
        self.assert_refused()

    def test_divergent_commit_preserved(self):
        (self.repo / "tracked").write_text("local commit")
        self.commit(self.repo)
        (self.remote / "tracked").write_text("upstream commit")
        self.commit(self.remote)
        self.assert_refused()

    def test_detached_head_preserved(self):
        self.git(self.repo, "checkout", "--detach")
        self.assert_refused()

    def test_wrong_branch_refused(self):
        self.git(self.repo, "checkout", "-b", "my-work")
        self.assert_refused()
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "my-work")

    def test_wrong_origin_refused(self):
        self.git(self.repo, "remote", "set-url", "origin", str(self.remote))
        self.assert_refused()

    def test_clean_fast_forward(self):
        (self.remote / "tracked").write_text("upstream\n")
        self.commit(self.remote)
        result = self.run_checkout()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.repo / "tracked").read_text(), "upstream\n")

    def test_new_checkout_supported(self):
        self.repo.rename(self.base / "old-checkout")
        result = self.run_checkout()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.repo / "tracked").read_text(), "original\n")

    def test_git_file_worktree_supported(self):
        linked = self.base / "original-checkout"
        self.repo.rename(linked)
        self.git(linked, "checkout", "--detach")
        self.git(linked, "worktree", "add", str(self.repo), "master")
        result = self.run_checkout()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.repo / ".git").is_file())

    def add_submodule(self):
        sub = self.base / "sub-source"
        self.git(self.base, "init", "-b", "master", str(sub))
        (sub / "data").write_text("original")
        (sub / ".gitignore").write_text("private.local\n")
        self.commit(sub)
        self.git(self.repo, "submodule", "add", str(sub), "module")
        self.commit(self.repo)
        self.git(self.remote, "fetch", str(self.repo), "master")
        self.git(self.remote, "merge", "--ff-only", "FETCH_HEAD")

    def test_dirty_submodule_preserved(self):
        self.add_submodule()
        (self.repo / "module" / "data").write_text("local")
        self.assert_refused()
        self.assertEqual((self.repo / "module" / "data").read_text(), "local")

    def test_ignored_submodule_preserved(self):
        self.add_submodule()
        (self.repo / "module" / "private.local").write_text("private fixture")
        self.assert_refused()

    def test_submodule_commit_preserved(self):
        self.add_submodule()
        sub = self.repo / "module"
        (sub / "data").write_text("local commit")
        self.commit(sub)
        before = self.git(sub, "rev-parse", "HEAD")
        self.assert_refused()
        self.assertEqual(self.git(sub, "rev-parse", "HEAD"), before)


class MicrophoneTests(unittest.TestCase):
    def mic_phase(self, opt_in):
        source = INSTALLER.read_text(encoding="utf-8")
        # Evaluate only this phase, replacing pactl with a shell function so
        # even a regressed unconditional call cannot touch real audio.
        phase = source.split("# Set PipeWire mic capture volume", 1)[1].split(
            "if command -v steamos-add-to-steam", 1)[0]
        phase = "# Set PipeWire mic capture volume" + phase
        script = 'pactl() { printf "PACTLCALL:%s\\n" "$*"; };\n' + phase
        env = os.environ.copy()
        env.pop("VIBELIGHT_SET_MIC_VOLUME", None)
        if opt_in is not None:
            env["VIBELIGHT_SET_MIC_VOLUME"] = opt_in
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", script],
                              env=env, text=True, capture_output=True, check=True).stdout

    def test_default_microphone_untouched(self):
        self.assertNotIn("PACTLCALL:", self.mic_phase(None))

    def test_explicit_opt_in_sets_volume(self):
        self.assertIn("PACTLCALL:set-source-volume @DEFAULT_SOURCE@ 50%", self.mic_phase("1"))

    def test_non_opt_in_values_do_not_set_volume(self):
        self.assertNotIn("PACTLCALL:", self.mic_phase("0"))


if __name__ == "__main__":
    unittest.main()
