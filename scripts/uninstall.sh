#!/bin/zsh
set -euo pipefail

root_dir=${0:A:h:h}
yes=0
remove_driver=0
while (( $# )); do
  case "$1" in
    --yes) yes=1 ;;
    --remove-driver) remove_driver=1 ;;
    -h|--help)
      print "Usage: ./scripts/uninstall.sh --yes [--remove-driver]"
      exit 0
      ;;
    *) print -u2 "Unknown option: $1"; exit 2 ;;
  esac
  shift
done

if (( ! yes )); then
  print -u2 "Uninstall removes /Applications/CardBridge.app. Re-run with --yes."
  exit 2
fi

osascript -e 'tell application "CardBridge" to quit' >/dev/null 2>&1 || true
rm -rf /Applications/CardBridge.app
if (( remove_driver )); then
  "${root_dir}/bridge/driver/uninstall_driver.sh"
fi
print "CardBridge App removed. Pairing data was preserved."
