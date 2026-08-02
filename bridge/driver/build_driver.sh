#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
build_dir=${script_dir}/build
bundle=${build_dir}/CardBridgeMicrophone.driver
contents=${bundle}/Contents
binary=${contents}/MacOS/CardBridgeMicrophone
identity=${CODE_SIGN_IDENTITY:--}

mkdir -p "${contents}/MacOS" "${contents}/Resources"
ditto "${script_dir}/Info.plist" "${contents}/Info.plist"

xcrun --sdk macosx clang \
  -std=gnu11 \
  -fblocks \
  -O2 \
  -arch arm64 \
  -arch x86_64 \
  -mmacosx-version-min=11.0 \
  -DDEBUG=0 \
  -bundle \
  -framework CoreAudio \
  -framework CoreFoundation \
  -framework Accelerate \
  "${script_dir}/upstream/CardBridgeMicrophone.c" \
  -o "${binary}"

if [[ -f "${script_dir}/../macos/App/CardBridge.icns" ]]; then
  ditto "${script_dir}/../macos/App/CardBridge.icns" \
    "${contents}/Resources/CardBridgeMicrophone.icns"
fi

codesign --force --options runtime --timestamp=none --sign "${identity}" "${bundle}"
codesign --verify --strict --verbose=2 "${bundle}"
echo "Built ${bundle}"
