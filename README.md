# gitwho

Which git identity will your next commit *actually* use — and where it came
from.

`git config user.email` gives you the value. It doesn't tell you whether that
value came from the repo's local config, your global `~/.gitconfig`, a
conditional `includeIf` file for a client directory, or whether
`GIT_AUTHOR_EMAIL` in the environment will silently override all of them.
That last one is the classic multi-client footgun: the config looks right,
the commit lands under the wrong identity.

gitwho resolves the effective `user.name` / `user.email` and reports the
source of each: `local (.git/config)`, `global`, `system`, `included file
(<path>)`, `-c flag`, or `environment (GIT_AUTHOR_NAME/EMAIL)`. Environment
overrides are checked first, because git checks them first.

## Usage

```bash
gitwho                  # resolve for the current directory
gitwho ~/work/client-x  # resolve for another directory
gitwho --json           # machine-readable report
```

Exit codes: `0` identity complete · `1` identity incomplete (the next commit
would fail with "author identity unknown") · `2` usage error. `--version`
prints the version.

The report also notes: committer/author divergence (`GIT_COMMITTER_*` set and
different), `user.useConfigOnly=true` (git won't guess identity from the
system), a configured `user.signingkey`, and non-repo directories (no local
scope to resolve).

## Design notes

- **git is the authority.** Resolution delegates to `git config
  --show-origin`; there is no reimplementation of config precedence to go
  stale. Environment precedence (`GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` beat
  config) follows the documented git behavior.
- **Read-only.** gitwho never writes config. There is no `set` subcommand
  by design — this is a diagnostic, not a config editor.
- Origin classification is honest about what it can't know: any config file
  that isn't system/global/local scope is labeled `included file (<path>)`
  rather than guessing which `includeIf` rule pulled it in.

## Known limitations

- Multi-line config values are not specially handled (pathological for
  name/email; reported verbatim on one line).
- Worktree-specific `config.worktree` overrides are not separately labeled;
  they appear under their file origin like any other.
- Only author/committer identity is resolved — no other config keys.

## Pre-publish checklist

- [ ] Secrets scan: `gitleaks detect --source .` clean (no credentials in
      repo or history)
- [ ] History review: `git log --oneline` — every commit intentional
- [ ] License: MIT (pending Godsby's approval of the license choice)
- [ ] Godsby's approval before first publication
