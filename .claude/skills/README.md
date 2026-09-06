# Skills

Not used yet in this repo. Placeholder so the directory survives in git.

A skill is a subfolder here with a `SKILL.md` (frontmatter: `name`,
`description`) plus any bundled scripts/resources it needs. Unlike
`.claude/commands/`, skills are auto-loaded by Claude when the description
matches what's being discussed — no explicit `/name` invocation required.

Add one when something should trigger automatically from conversation
context rather than being asked for by name. Until then, `.claude/commands/`
(`run-eval`, `triage`) covers this repo's needs.
