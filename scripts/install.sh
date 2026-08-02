#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
root_dir=${script_dir:h}
source_app=${root_dir}/bridge/macos/dist/CardBridge.app
target_app=/Applications/CardBridge.app
open_app=1

while (( $# )); do
  case "$1" in
    --no-open) open_app=0 ;;
    -h|--help)
      print "Usage: ./scripts/install.sh [--no-open]"
      exit 0
      ;;
    *) print -u2 "Unknown option: $1"; exit 2 ;;
  esac
  shift
done

[[ -d "${source_app}" ]] || {
  print -u2 "${source_app} is missing. Run ./scripts/build.sh first."
  exit 1
}
"${root_dir}/bridge/agent/.venv/bin/python" "${root_dir}/tools/validate_release.py" --app "${source_app}"
osascript -e 'tell application "CardBridge" to quit' >/dev/null 2>&1 || true
"${root_dir}/scripts/replace_app.sh" "${source_app}"
if (( open_app )); then
  open "${target_app}"
fi
print "The App will request any required driver and macOS permissions."
