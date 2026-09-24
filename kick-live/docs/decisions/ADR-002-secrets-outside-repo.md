# ADR-002: Secrets live outside the repository

Status: accepted (2026-09-24)

## Context
The stream key and SRT passphrase must never be committed. The previous session was interrupted
while about to write them to a gitignored `kick-live/.env`.

## Decision
Secrets live at `~/.config/kick-live/env` (mode 600, directory 700). `scripts/env.sh` sources that
file; `KICK_LIVE_ENV` overrides the path. `.env.example` in the repo documents the variables. A
pre-commit hook (`scripts/pre-commit`, installed by `scripts/install-hooks.sh`) refuses commits
containing key, passphrase, token or private-key patterns.

## Consequences
- A fresh clone needs `scripts/install-hooks.sh` and a filled env file before `start.sh` works.
- The stream key was pasted into a chat earlier today and should be rotated after this project.
