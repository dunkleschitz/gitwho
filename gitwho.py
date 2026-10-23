#!/usr/bin/env python3
"""gitwho — which git identity will your next commit actually use, and where it came from.

`git config user.email` tells you the value. gitwho tells you the value,
*which file set it* (local / global / system / included file), and whether an
environment override (GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL) will silently win
over all of them — the thing that actually bites people with multi-client
includeIf setups and agent-driven commits.

Exit codes: 0 identity complete · 1 identity incomplete (commit would fail) ·
2 usage error. Read-only: never writes config.
"""

import json
import os
import shutil
import subprocess
import sys

VERSION = "1.0.0"

KEYS = ("user.name", "user.email")
ENV_AUTHOR = (("GIT_AUTHOR_NAME", "user.name"), ("GIT_AUTHOR_EMAIL", "user.email"))
ENV_COMMITTER = (("GIT_COMMITTER_NAME", "user.name"), ("GIT_COMMITTER_EMAIL", "user.email"))


def _git(args, cwd):
    """Run git, return (rc, stdout). git missing -> raise."""
    try:
        p = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=15
        )
    except FileNotFoundError:
        raise RuntimeError("git not found on PATH")
    return p.returncode, p.stdout


def _git_dir(target):
    rc, out = _git(["rev-parse", "--absolute-git-dir"], target)
    if rc != 0:
        return None
    return out.strip()


def _config_get(key, target):
    """Return (origin, value) or (None, None) if unset. Origin is raw, e.g.
    'file:/home/u/.gitconfig'. Observed format: '<origin>\\t<value>'."""
    rc, out = _git(["config", "--show-origin", "--get", key], target)
    if rc != 0:
        return None, None
    line = out.rstrip("\n")
    if "\t" not in line:
        return "?", line
    origin, _, value = line.partition("\t")
    return origin, value


def _classify_origin(origin, gitdir, target):
    """Turn a raw origin into a human scope label. git reports the local
    config with a target-relative path (observed: 'file:.git/config'), so
    relative origins resolve against the target directory."""
    if origin is None:
        return "unset"
    if origin == "command line:":
        return "-c flag"
    if origin.startswith("file:"):
        raw = os.path.expanduser(origin[len("file:"):])
        path = raw if os.path.isabs(raw) else os.path.join(target, raw)
        path = os.path.abspath(path)
        if gitdir and path == os.path.join(gitdir, "config"):
            return "local (.git/config)"
        home = os.path.expanduser("~")
        candidates = [
            os.environ.get("GIT_CONFIG_GLOBAL"),
            os.path.join(home, ".gitconfig"),
            os.path.join(home, ".config", "git", "config"),
        ]
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            candidates.append(os.path.join(xdg, "git", "config"))
        for c in candidates:
            if c and path == os.path.abspath(os.path.expanduser(c)):
                return "global"
        sys_candidates = [
            os.environ.get("GIT_CONFIG_SYSTEM"),
            "/etc/gitconfig",
        ]
        for c in sys_candidates:
            if c and path == os.path.abspath(os.path.expanduser(c)):
                return "system"
        return "included file (%s)" % origin[len("file:"):]
    return origin  # e.g. environment-injected config; surface verbatim


def resolve(target):
    """Return dict with identity resolution. Pure data; no printing."""
    gitdir = _git_dir(target)
    result = {
        "directory": os.path.abspath(target),
        "in_repo": gitdir is not None,
        "identity": {},
        "env_overrides": {},
        "notes": [],
        "warnings": [],
        "errors": [],
    }

    for env_var, key in ENV_AUTHOR:
        val = os.environ.get(env_var)
        if val:
            result["env_overrides"][key] = (val, "environment (%s)" % env_var)

    for key in KEYS:
        if key in result["env_overrides"]:
            value, source = result["env_overrides"][key]
        else:
            origin, value = _config_get(key, target)
            source = _classify_origin(origin, gitdir, target)
        result["identity"][key] = {"value": value, "source": source}

    for env_var, key in ENV_COMMITTER:
        val = os.environ.get(env_var)
        if val:
            author_val = result["identity"][key]["value"]
            if val != author_val:
                result["notes"].append(
                    "committer %s differs from author (%s=%s)"
                    % (key, env_var, val)
                )

    name = result["identity"]["user.name"]["value"]
    email = result["identity"]["user.email"]["value"]
    if not name:
        result["errors"].append(
            "no user.name: the next commit would fail with 'author identity unknown'"
        )
    if not email:
        result["errors"].append(
            "no user.email: the next commit would fail with 'author identity unknown'"
        )

    if not result["in_repo"]:
        result["notes"].append("not a git repository: no local scope to resolve")

    _, use_config_only = _config_get("user.useConfigOnly", target)
    if use_config_only == "true":
        result["notes"].append(
            "user.useConfigOnly=true: git will not guess identity from the system"
        )

    _, signingkey = _config_get("user.signingkey", target)
    if signingkey:
        result["notes"].append("commits will be signed with key %s" % signingkey)

    return result


def render_text(res):
    lines = ["identity for %s:" % res["directory"]]
    for key in KEYS:
        info = res["identity"][key]
        value = info["value"] if info["value"] else "<unset>"
        lines.append("  %-10s %-32s (%s)" % (key, value, info["source"]))
    for n in res["notes"]:
        lines.append("  note: %s" % n)
    for w in res["warnings"]:
        lines.append("  warn: %s" % w)
    for e in res["errors"]:
        lines.append("  ERROR: %s" % e)
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if not a.startswith("-")]
    flags = [a for a in argv if a.startswith("-")]
    if "--version" in flags:
        print("gitwho %s" % VERSION)
        return 0
    if "-h" in flags or "--help" in flags:
        print(__doc__.strip())
        print("\nusage: gitwho [DIR] [--json] [--version]")
        return 0
    unknown = [f for f in flags if f not in ("--json",)]
    if unknown:
        print("gitwho: unknown flag(s): %s" % " ".join(unknown), file=sys.stderr)
        return 2
    if len(args) > 1:
        print("gitwho: expected at most one directory", file=sys.stderr)
        return 2
    target = args[0] if args else os.getcwd()
    if not os.path.isdir(target):
        print("gitwho: not a directory: %s" % target, file=sys.stderr)
        return 2
    try:
        res = resolve(target)
    except RuntimeError as e:
        print("gitwho: %s" % e, file=sys.stderr)
        return 2

    if "--json" in flags:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print(render_text(res))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
