#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
macos_dir=${script_dir:h}
source_icon=${macos_dir}/App/AppIcon-1024.png
iconset=${macos_dir}/.build/AppIcon.iconset
output=${macos_dir}/App/CardBridge.icns

[[ -f "${source_icon}" ]] || {
  print -u2 "Missing ${source_icon}"
  exit 1
}

mkdir -p "${iconset}"
for spec in \
  '16 icon_16x16.png' \
  '32 icon_16x16@2x.png' \
  '32 icon_32x32.png' \
  '64 icon_32x32@2x.png' \
  '128 icon_128x128.png' \
  '256 icon_128x128@2x.png' \
  '256 icon_256x256.png' \
  '512 icon_256x256@2x.png' \
  '512 icon_512x512.png' \
  '1024 icon_512x512@2x.png'; do
  size=${spec%% *}
  name=${spec#* }
  sips -z "${size}" "${size}" "${source_icon}" --out "${iconset}/${name}" >/dev/null
done
iconutil -c icns "${iconset}" -o "${output}"
print "Built ${output}"
