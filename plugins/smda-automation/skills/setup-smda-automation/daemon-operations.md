# SMDA Daemon Operations

Optional, approval-gated Tier-3 artifacts for running the SMDA Scheduler daemon
against a configured target repo. Everything here is **ops glue that invokes the
product CLI** — it must not reimplement scanner, routing, or phase-machine logic
(that is product code; see Hard Gate 7 in SKILL.md). Write these only when the
user explicitly asks to operate the daemon, and never start a live loop during
setup or refresh.

## 1. Populate the Linear adapter environment

The backlog adapter reads credentials and IDs from the process environment, not
from committed config (see [adapters.md](adapters.md)). A fresh setup must put
these into a gitignored local env file (e.g. `.env`):

- `LINEAR_API_KEY` — secret.
- `SMDA_LINEAR_TEAM_ID` — the Linear team UUID.
- `SMDA_LINEAR_PROJECT_ID` — optional Linear project UUID. When set, the adapter
  scopes both the issue scan and child creation to that project, so multiple
  SMDA-managed repos can share one team without cross-dispatching each other's
  work. This is the recommended multi-repo isolation default
  (`config.adapters.backlog.scope_id` is the human reference for it); unset means
  team-wide scanning, which is unsafe when repos share a team. **One project per
  repo.** If the repo's project already exists, fetch its id read-only (query
  below). If it does not, creating it is a **live tracker mutation** — confirm
  with the user first, like creating states/labels (§ end of this section), then
  fetch the new id.
- `SMDA_LINEAR_STATE_<NAME>` — one per tracker state the phase machine drives
  (at minimum `TODO`; in practice the full set the tracker contract uses:
  `TODO`, `IN_PROGRESS`, `AGENT_REVIEW`, `HUMAN_REVIEW`, `BLOCKED`, `DONE`,
  `CANCELED`). The env-var suffix maps to a Linear state name via
  `suffix.replace("_"," ").title()` — so `SMDA_LINEAR_STATE_IN_PROGRESS` →
  state `In Progress`. The value is the state's UUID.
- `SMDA_LINEAR_LABEL_<NAME>` — label UUIDs the engine reads/writes. The suffix
  maps via `suffix.lower().replace("_","-")`. The engine programmatically stamps
  only the actor label (`agent`); execution modes (`Execution: smda` /
  `Execution: smda-child`) are **issue body markers, not labels**, so they need
  no label entry.

The team/state/label UUIDs can be fetched **read-only** with the user's existing
key — this is inspection, not a live tracker mutation, but still confirm before
sending any request to the tracker. Example (Linear GraphQL):

```bash
# Authorization header takes the raw personal API key (no "Bearer").
# 1) teams -> pick the team id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ teams(first:50){ nodes{ id key name } } }"}'

# 2) states + labels for that team id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query($id:String!){ team(id:$id){ states(first:50){nodes{id name type}} labels(first:100){nodes{id name}} } }","variables":{"id":"<TEAM_ID>"}}'

# 3) projects on that team -> pick (or confirm absence of) this repo's project id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query($id:String!){ team(id:$id){ projects(first:100){nodes{id name}} } }","variables":{"id":"<TEAM_ID>"}}'
```

Map the returned ids to the env-var names above and write them to the gitignored
env file. Do not create, rename, or delete tracker states/labels — that is a live
adapter mutation requiring explicit approval. Creating a Linear **project** for a
new repo is the same class of live mutation: confirm first, then create with
`projectCreate` (e.g. `mutation{ projectCreate(input:{name:"<repo>",teamIds:["<TEAM_ID>"]}){ project{ id } } }`)
and record the returned id as `SMDA_LINEAR_PROJECT_ID`.

**Onboarding additional repos to an existing team (multi-repo).** States and
labels are team-scoped, so their ids are identical across every repo on that
team. Only the project differs. Shortcut: copy the `SMDA_LINEAR_TEAM_ID`,
`SMDA_LINEAR_STATE_*`, and `SMDA_LINEAR_LABEL_*` lines verbatim from the template
repo's env, then set just `SMDA_LINEAR_PROJECT_ID` to the new repo's project id
and `config.adapters.backlog.scope_id` to a distinct human reference for it. No
need to re-fetch states/labels per repo.

Validate config + context before any run:

```bash
uv run --project <smda-product-root> smda-scheduler validate-config <config> --repo-root <repo>
uv run --project <smda-product-root> smda-scheduler validate-context <config> --repo-root <repo>
```

## 2. Daemon invocation model

```bash
smda-scheduler daemon <config> --repo-root <repo> --state Todo --label agent --owner smda-daemon
```

`--max-ticks` defaults to **1**: one tick per invocation, then exit. The engine
is intentionally not a self-driving daemon — continuous running is an external
concern. A single tick = retry pending tracker effects → scan the tracker by
state+label → classify → dispatch one candidate (synchronous, blocking).

Two ways to run continuously:

- **External scheduler** (launchd/systemd/cron) re-invokes one bounded tick on a
  cadence; or
- a **foreground loop** in an interactive terminal/tmux (template below).

### macOS caveat (TCC)

launchd and cron jobs cannot access TCC-protected folders (`~/Desktop`,
`~/Documents`, `~/Downloads`). If the repo (or the SMDA product checkout) lives
under one of these, a launchd/cron job fails with `Operation not permitted`. An
interactive terminal already holds the Desktop grant, so use the foreground loop
there (or move the repos out of the protected folder for a permanent fix).

## 3. Foreground daemon loop template

A per-tick loop that sources the env file, survives a failing tick, and enforces
**one daemon per repo**. The single-daemon guard matters: two concurrent
scanners can double-dispatch a `Todo` issue in the window before its state flips
off the scan filter (parent intake has no cross-process mutex). An atomic
`mkdir` lock enforces single ownership and reclaims a lock left by a dead holder.

```bash
#!/usr/bin/env bash
# Foreground continuous SMDA Scheduler daemon loop.
# Run in an interactive terminal (or tmux) that has filesystem access to the
# repo. Each iteration runs ONE bounded tick; a failing tick does not kill the
# loop. Ctrl-C stops. Usage: smda-daemon-loop.sh [interval_seconds]  # default 30
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SMDA_PROJECT="<smda-product-root>"
INTERVAL="${1:-30}"

cd "$REPO_ROOT"
set -a; [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"; set +a

# --- single-daemon guard ---
LOCK_DIR="$REPO_ROOT/.smda/smda-daemon-loop.lock"
release_lock() { rm -rf "$LOCK_DIR"; }
acquire_lock() {
  mkdir -p "$REPO_ROOT/.smda"
  if mkdir "$LOCK_DIR" 2>/dev/null; then printf '%s\n' "$$" > "$LOCK_DIR/pid"; return 0; fi
  local other; other="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$other" =~ ^[0-9]+$ ]] && kill -0 "$other" 2>/dev/null; then
    printf 'error: another SMDA daemon loop is already running (pid %s)\n' "$other" >&2; exit 3
  fi
  printf 'reclaiming stale lock from pid %s\n' "${other:-unknown}" >&2
  rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR" 2>/dev/null || { printf 'error: cannot acquire lock\n' >&2; exit 3; }
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
}
acquire_lock
trap 'release_lock' EXIT
trap 'printf "\nstopped\n"; exit 0' INT TERM

printf 'SMDA daemon loop: interval=%ss  repo=%s  pid=%s  (Ctrl-C to stop)\n' "$INTERVAL" "$REPO_ROOT" "$$"
while true; do
  uv run --project "$SMDA_PROJECT" smda-scheduler daemon "$REPO_ROOT/smda.config.json" \
    --repo-root "$REPO_ROOT" --state Todo --label agent --owner smda-daemon --max-ticks 1 \
    || printf 'tick exited non-zero; continuing\n'
  sleep "$INTERVAL"
done
```

If a long-lived single nohup process is preferred instead of a per-tick loop,
pass an explicit large `--max-ticks` (omitting it runs a single tick because the
CLI default is 1). The per-tick loop is more resilient: a single process exits
when any one tick raises, whereas the loop continues to the next tick.

A `.smda/smda-daemon-loop.lock` dir (pid inside) is the **single liveness
marker** for the daemon. Give the script a read-only `status` subcommand that
inspects the lock (`kill -0` on the pid) and reports running / not running
without starting anything — do not maintain a second, separate pidfile mechanism
that can disagree with the lock.

## 4. Operator command surface

Surface the full SMDA Scheduler CLI in the harness so a session can inspect and
control the runtime. All commands take the config + `--repo-root`:

| Command | Read/Write | Use |
|---|---|---|
| `validate-config` | read | Boot the config; report workspace id + ledger/artifact paths. |
| `validate-context` | read | Verify bootloader/spec/ADR/quality-gate paths resolve. |
| `status` | read | Full runtime state: parent runs, per-child phase/attempts/claim owner/backoff, paused parents. |
| `validate-state` | read | Terse health: workspace id + ledger path only. |
| `pause --parent <id>` | write | Pause a parent — its children are skipped on dispatch. |
| `resume --parent <id>` | write | Un-pause a parent. |
| `reconcile-claims` | write | Release expired child claims (crashed-worker leases). |
| `daemon` | live | Scan + dispatch one bounded tick; autonomous. Run via the loop wrapper, not directly. |

`pause`/`resume`/`reconcile-claims` mutate the ledger only (not tracker or git) —
safe operator controls. `daemon` is the one autonomous-action command; keep it
approval-gated. Surface these as documented shell commands the agent runs via the
product CLI — do not wrap them in a setup-generated MCP server or other runtime
code (Hard Gate 7). If model-driven control is later wanted, the MCP server is a
product-owned entrypoint exposed through a `.mcp.json` pointer, not setup output.

## 5. Bootloader status check (read-only)

The daemon is session-independent: it drains the tracker whether or not anyone
has a dev session open. So do not couple "start the daemon" to "start a dev
session". Instead, have the harness bootloader/routing tell a fresh session to
**check and report** daemon status at the start (read-only), so it is clear
whether tracker issues will be picked up:

```bash
<repo>/docs/harness/smda-daemon-loop.sh status   # reports running / not; read-only
```

The bootloader must **not auto-start** the daemon — starting an autonomous,
auto-merging loop requires explicit human approval (see adapters.md). If it is
down and the user wants autonomous dispatch, offer to start it; the user runs the
loop in a terminal/tmux. Put this pointer in the harness routing (e.g.
`docs/harness/index.md`), not duplicated in the bootloader file.

## 6. Concurrency contract

Re-dispatch safety holds **per repo for a single daemon process**: the tracker
state transition off the scan filter, the ledger parent-run (resume not
restart), durable idempotent tracker effects, child claim+lease, and sequential
ticks together prevent double work. There is no cross-process mutex on the
parent intake scan, so the single-daemon guard above is the safeguard against
running two schedulers against the same repo.
