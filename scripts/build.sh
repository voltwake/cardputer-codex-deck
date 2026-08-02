#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
root_dir=${script_dir:h}
pio_bin=${root_dir}/tools/.venv/bin/pio
firmware_dir=${root_dir}/firmware/m5stack-cardputer-adv
macos_dir=${root_dir}/bridge/macos
venv_python=${root_dir}/bridge/agent/.venv/bin/python

cd "${root_dir}"
if [[ -x "${pio_bin}" ]]; then
  "${pio_bin}" run -d "${firmware_dir}"
elif command -v pio >/dev/null 2>&1; then
  pio run -d "${firmware_dir}"
else
  print -u2 "PlatformIO is missing. Run ./scripts/bootstrap.sh first."
  exit 1
fi
"${macos_dir}/scripts/build_app.sh"
"${venv_python}" tools/validate_release.py --app "${macos_dir}/dist/CardBridge.app"
print "Build and package validation passed."
