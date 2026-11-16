# GitHub Catch-up Workflow

A Mistral Workflow that catches you up on a GitHub repository and posts the
digest to your Slack DMs.

## What it does

Given a repository handle (`owner/repo`) and a date (`YYYY-MM-DD`), the
`github-catchup` workflow:

1. Lists pull requests **merged since that date**.
2. Lists **open pull requests waiting on review** (no review yet, or changes
   requested and awaiting re-review).
3. Posts a Slack DM to the user who started the run with one line per PR —
   title and link — in two sections.

The workflow runs **on behalf of the triggering user** (`on_behalf_of=True`):
GitHub and Slack credentials are resolved from that user's `github_app` and
`slack` connector connections, so every user gets their own digest in their
own DMs. The deployment must be hardened.

## Inputs

| Field   | Type   | Example        | Description                     |
| ------- | ------ | -------------- | ------------------------------- |
| `repo`  | string | `owner/repo`   | Repository handle (URLs accepted) |
| `since` | string | `2025-12-01`   | Only PRs merged on/after this date |

## Running

Start an execution with input:

```json
{"repo": "mistralai/client-python", "since": "2025-12-01"}
```

The workflow returns the Slack delivery confirmation; the digest appears in
your Slack DMs.

## Project layout

- `src/worker/workflows/github_catchup.py` — the workflow and its activities
- `src/worker/entrypoints/worker.py` — worker entrypoint (auto-discovers workflows)
- `tests/` — unit tests for parsing and digest formatting
- `Dockerfile` — worker image used by the managed deployment

## Local development

```bash
uv sync
uv run pytest
```
