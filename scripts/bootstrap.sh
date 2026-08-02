#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
root_dir=${script_dir:h}
python_bin=${PYTHON_BIN:-python3}

if ! command -v "${python_bin}" >/dev/null 2>&1; then
  print -u2 "Python 3.10+ was not found. Set PYTHON_BIN to an installed interpreter."
  exit 1
fi
if ! "${python_bin}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  print -u2 "Python 3.10 or newer is required."
  exit 1
fi

PYTHON_BIN="${python_bin}" "${root_dir}/bridge/macos/scripts/bootstrap_build_env.sh"
tool_venv="${root_dir}/tools/.venv"
if [[ ! -x "${tool_venv}/bin/python" ]]; then
  "${python_bin}" -m venv "${tool_venv}"
fi
"${tool_venv}/bin/python" -m pip install --disable-pip-version-check \
  "platformio==6.1.19"
"${root_dir}/bridge/macos/scripts/bootstrap_sparkle.sh"

print "CardBridge development environment is ready."
print "Next: ${root_dir}/scripts/test.sh"
