#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
macos_dir=${script_dir:h}
version=2.9.4
checksum=cb6fdbdc8884f15d62a616e79face92b08322410fd2d425edc6596ccbf4ba3b0
destination=${macos_dir}/.deps/Sparkle
framework=${destination}/Sparkle.xcframework

if [[ -d "${framework}" && -x "${destination}/bin/generate_appcast" ]]; then
  exit 0
fi

archive=$(mktemp "/tmp/Sparkle-${version}.XXXXXX.zip")
curl -fL \
  "https://github.com/sparkle-project/Sparkle/releases/download/${version}/Sparkle-for-Swift-Package-Manager.zip" \
  -o "${archive}"
actual=$(swift package compute-checksum "${archive}")
if [[ "${actual}" != "${checksum}" ]]; then
  print -u2 "Sparkle checksum mismatch: expected ${checksum}, got ${actual}"
  exit 1
fi

mkdir -p "${destination}"
ditto -x -k "${archive}" "${destination}"
codesign --verify --deep --strict --verbose=2 \
  "${framework}/macos-arm64_x86_64/Sparkle.framework"
print "Bootstrapped Sparkle ${version}"
