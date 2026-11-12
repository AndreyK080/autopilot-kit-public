---
name: autopilot-setup
description: Use when the user asks to set up or change Autopilot roles, models, effort or their subscription plan. Interactive wizard that writes the autopilot-kit profile.
---

# Autopilot setup wizard

You help the owner choose which model and effort each Autopilot role runs on, then write the profile.
Ask one question at a time. Answer in the owner's language.

## 1. Find the kit

All commands below are `python -m kit ...` and must run with the autopilot-kit repository (the folder
that contains `kit/` and `pyproject.toml`) as the working directory. If you are not there, ask the owner
for its path once and use it as the working directory of the commands. Do not search the disk.

## 2. Ask the subscription plan

Detect the app (`CLAUDE_CODE_ENTRYPOINT` = `claude-desktop-3p` → **Claude Desktop Gate**, the gateway drive D48;
`CODEX_THREAD_ID` set → Codex; otherwise `CLAUDECODE` set → Claude Code; `ANTHROPIC_BASE_URL` is **not** a marker —
the subscription app sets it to its own local proxy too, T19.8) and ask only about it:

- Claude: Pro / Max 5x / Max 20x
- Claude Desktop Gate: no plan question — traffic goes through the organization's gateway (subscription
  of the organization, not Anthropic); say one line that the `desktop-gate` preset applies
- Codex: Plus / Pro / other

## 3. Propose a preset

- Claude Desktop Gate → `desktop-gate`: the gateway maps the middle alias (sonnet) to a flash model, so
  the executor runs on the strong tier, like the reviewers. On this drive also propose pinning it in step 5
  (`--drive claude-gate`): the pin overrides environment detection, which can be wrong in both directions (D49).
- Pro (Claude) or Plus (Codex) → `economy`. Everything else → `quality`.

Show the table without writing anything:

```
python -m kit profile set --preset <economy|quality> --dry-run
```

Print its output as a table «роль → модель → усилие» (it shows both vendors). Roles: `executor`,
`reviewer-spec`, `reviewer-craft`, `final-reviewer`. Tiers: `strong`, `balanced`, `fast`.
Efforts: `low`, `medium`, `high`, `xhigh`, `max`.

## 4. Offer changes

Ask whether to change any role. For each change take `role`, `tier`, `effort`. Show the table again
with the changes, adding `--role <role>=<tier>:<effort>` once per change to the same `--dry-run` command.
Repeat until the owner says it is fine. Never change a role the owner did not ask about.

## 5. Write it

Only after the owner's explicit yes, run the same command without `--dry-run`:

```
python -m kit profile set --preset <p> --role executor=balanced:medium --role ... [--drive claude-gate]
```

It writes `~/.autopilot-kit/profile.toml`, recalculates `~/.autopilot-kit/resolved.json` and
regenerates the `autopilot-*` agents. Report its output in one or two lines.

## 6. Tell the owner what happens next

Claude Code reads agent files at the start of a chat: the new settings apply in a **new chat**.
The model of the main chat (the orchestrator) is chosen by the owner in the app and is not changed
by this wizard; recommend the strongest model available.
