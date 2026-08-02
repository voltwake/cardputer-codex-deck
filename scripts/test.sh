#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
root_dir=${script_dir:h}
agent_dir=${root_dir}/bridge/agent
macos_dir=${root_dir}/bridge/macos
firmware_dir=${root_dir}/firmware/m5stack-cardputer-adv
venv_python=${agent_dir}/.venv/bin/python
pio_bin=${root_dir}/tools/.venv/bin/pio

[[ -x "${venv_python}" ]] || {
  print -u2 "bridge/agent/.venv is missing. Run ./scripts/bootstrap.sh first."
  exit 1
}

cd "${root_dir}"
"${venv_python}" tools/check_project.py
"${venv_python}" tools/generate_versions.py --check
PYTHONPATH="${agent_dir}:${root_dir}" "${venv_python}" -m unittest discover \
  -s "${agent_dir}/tests" -v
swift test --package-path "${macos_dir}"
if [[ -x "${pio_bin}" ]]; then
  "${pio_bin}" run -d "${firmware_dir}"
elif command -v pio >/dev/null 2>&1; then
  pio run -d "${firmware_dir}"
else
  print -u2 "PlatformIO is required for the firmware test."
  exit 1
fi
git diff --check
print "All CardBridge checks passed."
