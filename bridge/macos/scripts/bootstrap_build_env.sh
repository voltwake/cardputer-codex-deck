#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
repo_dir=${script_dir:h:h:h}
agent_dir=${repo_dir}/bridge/agent
venv=${agent_dir}/.venv
python_bin=${PYTHON_BIN:-python3}

if ! command -v "${python_bin}" >/dev/null 2>&1; then
  print -u2 "Python executable not found: ${python_bin}"
  exit 1
fi
if ! "${python_bin}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  print -u2 "Python 3.10 or newer is required (set PYTHON_BIN to override)."
  exit 1
fi

if [[ ! -x "${venv}/bin/python" ]]; then
  "${python_bin}" -m venv "${venv}"
fi
if ! "${venv}/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  print -u2 "${venv} was created with Python older than 3.10; remove it and rerun bootstrap."
  exit 1
fi
"${venv}/bin/python" -m pip install --disable-pip-version-check \
  -c "${agent_dir}/constraints-macos-arm64-py310.txt" \
  -e "${agent_dir}" \
  -r "${agent_dir}/requirements-build.txt"
