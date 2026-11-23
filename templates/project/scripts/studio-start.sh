#!/bin/sh
# Alpa Studio launcher. Default = autonomous mode: an external orchestrator runs one fresh
# Claude process per task until no eligible work remains (no /clear or continue phrase needed).
#   scripts/studio-start.sh                 -> autonomous loop (alpa run)
#   scripts/studio-start.sh --interactive   -> one interactive Claude session (manual fallback)
#   scripts/studio-start.sh --max-tasks 3   -> extra flags are passed to `alpa run`
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
if [ "${1:-}" = "--interactive" ]; then
  exec claude "start"
fi
exec "$PROJECT_ROOT/scripts/alpa" run "$@"
