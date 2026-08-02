#!/bin/zsh
set -euo pipefail

if (( $# != 2 )); then
  print -u2 "Usage: create_dmg.sh /path/to/CardBridge.app /path/to/CardBridge-version.dmg"
  exit 2
fi

app=${1:A}
output=${2:A}
[[ -d "${app}" ]] || {
  print -u2 "App bundle not found: ${app}"
  exit 1
}

stage=$(mktemp -d /tmp/CardBridge-dmg.XXXXXX)
trap 'rm -rf "${stage}"' EXIT
ditto "${app}" "${stage}/CardBridge.app"
ln -s /Applications "${stage}/Applications"
mkdir -p "${output:h}"
rm -f "${output}"
hdiutil create \
  -volname "CardBridge" \
  -srcfolder "${stage}" \
  -format UDZO \
  -ov \
  "${output}"
hdiutil verify "${output}"
print "Built ${output}"
