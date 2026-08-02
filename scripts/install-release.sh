#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
root_dir=${script_dir:h}
repo_slug=${CARDBRIDGE_REPOSITORY:-voltwake/codex-deck}
version=latest
open_app=1

while (( $# )); do
  case "$1" in
    --version)
      shift
      (( $# )) || { print -u2 "--version requires a value"; exit 2; }
      version=$1
      ;;
    --no-open) open_app=0 ;;
    -h|--help)
      print "Usage: ./scripts/install-release.sh [--version VERSION] [--no-open]"
      exit 0
      ;;
    *) print -u2 "Unknown option: $1"; exit 2 ;;
  esac
  shift
done

tmp_dir=$(mktemp -d /tmp/CardBridge-install.XXXXXX)
trap 'rm -rf "${tmp_dir}"' EXIT
api_url="https://api.github.com/repos/${repo_slug}/releases"
if [[ "${version}" == latest ]]; then
  release_url="${api_url}/latest"
else
  version=${version#v}
  release_url="${api_url}/tags/v${version}"
fi
curl -fsSL -H 'Accept: application/vnd.github+json' "${release_url}" \
  -o "${tmp_dir}/release.json"

read -r dmg_url sums_url <<EOF
$(python3 - "${tmp_dir}/release.json" <<'PY'
import json
import sys

release = json.load(open(sys.argv[1], encoding="utf-8"))
assets = {item["name"]: item["browser_download_url"] for item in release.get("assets", [])}
dmg = next((url for name, url in assets.items() if name.endswith(".dmg")), "")
sums = assets.get("SHA256SUMS", "")
if not dmg or not sums:
    raise SystemExit("release does not contain a DMG and SHA256SUMS")
print(dmg, sums)
PY
)
EOF

curl -fL "${dmg_url}" -o "${tmp_dir}/CardBridge.dmg"
curl -fL "${sums_url}" -o "${tmp_dir}/SHA256SUMS"
(cd "${tmp_dir}" && grep 'CardBridge.*\.dmg$' SHA256SUMS | shasum -a 256 -c -)

mount_plist="${tmp_dir}/mount.plist"
hdiutil attach "${tmp_dir}/CardBridge.dmg" -nobrowse -plist -readonly >"${mount_plist}"
mount_point=$(python3 - "${mount_plist}" <<'PY'
import plistlib
import sys

data = plistlib.load(open(sys.argv[1], "rb"))
for entity in data.get("system-entities", []):
    point = entity.get("mount-point")
    if point:
        print(point)
        break
else:
    raise SystemExit("DMG mount point was not reported")
PY
)
trap 'hdiutil detach "${mount_point}" >/dev/null 2>&1 || true; rm -rf "${tmp_dir}"' EXIT
osascript -e 'tell application "CardBridge" to quit' >/dev/null 2>&1 || true
"${root_dir}/scripts/replace_app.sh" "${mount_point}/CardBridge.app"
hdiutil detach "${mount_point}" >/dev/null
print "Installed /Applications/CardBridge.app from ${release_url}"
if (( open_app )); then
  open /Applications/CardBridge.app
fi
print "Approve any administrator, Accessibility, Local Network, or Keychain prompts."
