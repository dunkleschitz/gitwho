# CHANGELOG — gitwho

## 1.0.0 (2026-10-22)

Initial release.

- Resolve the effective `user.name` / `user.email` for a directory and
  report each value's source: local / global / system / included file /
  `-c` flag / environment (`GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`, which
  override config per documented git behavior).
- Notes: committer-vs-author divergence, `user.useConfigOnly=true`,
  configured `user.signingkey`, non-repo directories.
- Exit codes 0 complete / 1 incomplete identity (commit would fail) /
  2 usage; `--json` machine report; `--version`.
- Read-only by design: delegates to `git config --show-origin`, never
  writes config.
- 16 tests passing (hermetic HOME/GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM;
  local/global/system/includeIf/env-override precedence, missing-identity
  gate, CLI surface).
