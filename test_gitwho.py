#!/usr/bin/env python3
"""Tests for gitwho. Hermetic: HOME, GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM
are redirected into a tmp dir and author/committer env vars are scrubbed, so
the operator's real git identity never leaks into fixtures."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

GITWHO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gitwho.py")
SCRUB = (
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_COUNT",
)


def run_gitwho(args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    for k, v in (env_extra or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    p = subprocess.run(
        [sys.executable, GITWHO] + args,
        capture_output=True, text=True, timeout=30, env=env,
    )
    return p.returncode, p.stdout, p.stderr


class Hermetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gitwho-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.base_env = {
            "HOME": self.home,
            "GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "global.gitconfig"),
            "GIT_CONFIG_SYSTEM": os.path.join(self.tmp, "system.gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        for f in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            open(self.base_env[f], "w").close()
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True,
                       env={**os.environ, **self.base_env})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None, env_extra=None):
        env = {**os.environ, **self.base_env, **(env_extra or {})}
        # git needs an identity only for commits; config writes don't.
        subprocess.run(["git", "-C", cwd or self.repo] + list(args),
                       check=True, capture_output=True, env=env)

    def who(self, *args, env_extra=None):
        env = dict(self.base_env)
        env.update(env_extra or {})
        return run_gitwho(list(args), env_extra=env)

    def who_json(self, *args, **kw):
        rc, out, _ = self.who(*args, "--json", **kw)
        return rc, json.loads(out)


class TestResolution(Hermetic):
    def test_local_wins_over_global(self):
        self.git("config", "user.name", "Local Name")
        self.git("config", "--global", "user.name", "Global Name")
        self.git("config", "--global", "user.email", "g@example.com")
        rc, res = self.who_json(self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(res["identity"]["user.name"]["value"], "Local Name")
        self.assertIn("local", res["identity"]["user.name"]["source"])
        self.assertEqual(res["identity"]["user.email"]["value"], "g@example.com")
        self.assertEqual(res["identity"]["user.email"]["source"], "global")

    def test_global_when_no_local(self):
        self.git("config", "--global", "user.name", "Just Global")
        self.git("config", "--global", "user.email", "jg@example.com")
        rc, res = self.who_json(self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(res["identity"]["user.name"]["source"], "global")

    def test_system_scope_labeled(self):
        # GIT_CONFIG_NOSYSTEM is on in the hermetic base env; drop it here.
        extra = dict(self.base_env)
        extra["GIT_CONFIG_NOSYSTEM"] = None
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        env.update({k: v for k, v in extra.items() if v is not None})
        subprocess.run(["git", "-C", self.repo, "config", "--system",
                        "user.name", "Sys Name"], check=True, env=env)
        subprocess.run(["git", "-C", self.repo, "config", "--system",
                        "user.email", "sys@example.com"], check=True, env=env)
        rc, out, err = run_gitwho([self.repo, "--json"], env_extra=extra)
        res = json.loads(out)
        self.assertEqual(rc, 0, err)
        self.assertEqual(rc, 0)
        self.assertEqual(res["identity"]["user.name"]["source"], "system")

    def test_includeif_labeled_included_file(self):
        inc = os.path.join(self.tmp, "work.gitconfig")
        with open(inc, "w") as f:
            f.write("[user]\n\tname = Work Name\n\temail = work@example.com\n")
        work = os.path.join(self.home, "work", "proj")
        os.makedirs(work)
        subprocess.run(["git", "init", "-q", work], check=True,
                       env={**os.environ, **self.base_env})
        with open(self.base_env["GIT_CONFIG_GLOBAL"], "w") as f:
            f.write('[includeIf "gitdir:%s/"]\n\tpath = %s\n'
                    % (os.path.join(self.home, "work"), inc))
        rc, res = self.who_json(work)
        self.assertEqual(rc, 0)
        self.assertEqual(res["identity"]["user.name"]["value"], "Work Name")
        self.assertTrue(
            res["identity"]["user.name"]["source"].startswith("included file"),
            res["identity"]["user.name"]["source"])

    def test_env_override_wins_and_is_reported(self):
        self.git("config", "user.name", "Local Name")
        self.git("config", "user.email", "local@example.com")
        rc, res = self.who_json(
            self.repo,
            env_extra={"GIT_AUTHOR_EMAIL": "env@example.com"})
        self.assertEqual(rc, 0)
        self.assertEqual(res["identity"]["user.email"]["value"], "env@example.com")
        self.assertIn("GIT_AUTHOR_EMAIL",
                      res["identity"]["user.email"]["source"])

    def test_committer_difference_noted(self):
        self.git("config", "user.name", "N")
        self.git("config", "user.email", "n@example.com")
        rc, res = self.who_json(
            self.repo,
            env_extra={"GIT_COMMITTER_EMAIL": "c@example.com"})
        self.assertEqual(rc, 0)
        self.assertTrue(any("committer" in n for n in res["notes"]), res["notes"])

    def test_missing_identity_exit_1(self):
        rc, out, _ = self.who(self.repo)
        self.assertEqual(rc, 1)
        self.assertIn("author identity unknown", out)

    def test_partial_identity_still_exit_1(self):
        self.git("config", "user.name", "Only Name")
        rc, _, _ = self.who(self.repo)
        self.assertEqual(rc, 1)

    def test_non_repo_resolves_without_local(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.git("config", "--global", "user.name", "G")
        self.git("config", "--global", "user.email", "g@example.com")
        rc, res = self.who_json(plain)
        self.assertEqual(rc, 0)
        self.assertFalse(res["in_repo"])
        self.assertTrue(any("not a git repository" in n for n in res["notes"]))

    def test_use_config_only_noted(self):
        self.git("config", "user.name", "N")
        self.git("config", "user.email", "n@example.com")
        self.git("config", "user.useConfigOnly", "true")
        _, res = self.who_json(self.repo)
        self.assertTrue(any("useConfigOnly" in n for n in res["notes"]))

    def test_signingkey_noted(self):
        self.git("config", "user.name", "N")
        self.git("config", "user.email", "n@example.com")
        self.git("config", "user.signingkey", "DEADBEEF")
        _, res = self.who_json(self.repo)
        self.assertTrue(any("DEADBEEF" in n for n in res["notes"]))


class TestCLI(Hermetic):
    def test_version(self):
        rc, out, _ = run_gitwho(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn("gitwho", out)

    def test_help(self):
        rc, out, _ = run_gitwho(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("usage", out.lower())

    def test_bad_dir_exit_2(self):
        rc, _, _ = self.who(os.path.join(self.tmp, "nope"))
        self.assertEqual(rc, 2)

    def test_unknown_flag_exit_2(self):
        rc, _, _ = self.who(self.repo, "--bogus")
        self.assertEqual(rc, 2)

    def test_text_output_shape(self):
        self.git("config", "user.name", "N")
        self.git("config", "user.email", "n@example.com")
        rc, out, _ = self.who(self.repo)
        self.assertEqual(rc, 0)
        self.assertIn("user.name", out)
        self.assertIn("user.email", out)
        self.assertIn("local", out)


if __name__ == "__main__":
    unittest.main()
