#!/bin/sh
set -eu
STUDIO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
usage() {
  echo "Usage: ./install.sh --project /absolute/UnityProject --profile example|PATH/TO/profile.json [--apply]"
  echo "Installs Alpa Studio into a Unity project. Safe default: without --apply, only a dry-run is performed."
  echo "Built-in profile: example (profiles/example.json). Or pass the path to your own profile JSON."
}
case "${1:-}" in
  "") usage >&2; exit 2 ;;
  -h|--help) usage; exit 0 ;;
esac
exec "$STUDIO_ROOT/bin/alpa" install "$@"
