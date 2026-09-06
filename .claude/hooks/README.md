# Hooks

Not used yet in this repo. Placeholder so the directory survives in git.

A hook is a shell script here, wired up in `.claude/settings.json`'s
`hooks` block, that runs on a tool-use event (`PreToolUse`, `PostToolUse`,
`Stop`, etc.) to automate or enforce something — not just document it.

Candidates identified for this repo but not yet built (would need explicit
sign-off before enabling, since a hook changes behavior silently):

- Block edits to `corpus/` — gitignored, meant to be regenerated from
  `SOURCES.md`, not hand-edited.
- Auto-run `generate_metadata.py --check` after any edit to `DOC_INFO` in
  `src/generate_metadata.py`.
- Warn/block on `git commit` touching anything under `corpus/`, as a
  backstop to `.gitignore` (FCA/ASIC licensing constraint — see
  `SOURCES.md`).
