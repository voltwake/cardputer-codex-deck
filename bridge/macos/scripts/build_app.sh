#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
macos_dir=${script_dir:h}
repo_dir=${macos_dir:h:h}
agent_dir=${repo_dir}/bridge/agent
driver_dir=${repo_dir}/bridge/driver
configuration=${CONFIGURATION:-release}
app_dir=${macos_dir}/dist/CardBridge.app
contents_dir=${app_dir}/Contents
agent_app=${contents_dir}/Helpers/CardBridgeAgent.app
agent_contents=${agent_app}/Contents

# A stable signing identity keeps macOS TCC grants valid across local
# rebuilds. CI and machines without a development certificate still fall
# back to ad-hoc signing, and callers can always override the identity.
identity=${CODE_SIGN_IDENTITY:-}
if [[ -z "${identity}" ]]; then
  identity=$(
    /usr/bin/security find-identity -v -p codesigning 2>/dev/null \
      | /usr/bin/sed -n 's/.*"\(Apple Development:[^"]*\)".*/\1/p' \
      | /usr/bin/head -n 1
  )
fi
identity=${identity:--}
export CODE_SIGN_IDENTITY=${identity}

"${macos_dir}/scripts/bootstrap_sparkle.sh"
"${macos_dir}/scripts/bootstrap_build_env.sh"
"${macos_dir}/scripts/build_icon.sh"
"${driver_dir}/build_driver.sh"
python3 "${repo_dir}/tools/generate_versions.py" --check
"${agent_dir}/.venv/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${macos_dir}/.build/agent-dist" \
  --workpath "${macos_dir}/.build/pyinstaller" \
  "${agent_dir}/packaging/CardBridgeAgent.spec"
swift build --package-path "${macos_dir}" -c "${configuration}"
bin_dir=$(swift build --package-path "${macos_dir}" -c "${configuration}" --show-bin-path)

rm -rf "${app_dir}"
mkdir -p \
  "${contents_dir}/Frameworks" \
  "${contents_dir}/MacOS" \
  "${contents_dir}/Resources" \
  "${contents_dir}/Helpers"
ditto "${bin_dir}/CardBridgeApp" "${contents_dir}/MacOS/CardBridge"
ditto "${bin_dir}/Sparkle.framework" "${contents_dir}/Frameworks/Sparkle.framework"
ditto "${macos_dir}/App/Info.plist" "${contents_dir}/Info.plist"
ditto "${macos_dir}/App/Resources" "${contents_dir}/Resources"
ditto "${macos_dir}/App/CardBridge.icns" "${contents_dir}/Resources/CardBridge.icns"
"${agent_dir}/.venv/bin/python" "${repo_dir}/tools/collect_licenses.py" \
  --output "${contents_dir}/Resources/Licenses"
mkdir -p "${contents_dir}/Resources/AudioDriver"
ditto "${driver_dir}/build/CardBridgeMicrophone.driver" \
  "${contents_dir}/Resources/AudioDriver/CardBridgeMicrophone.driver"
ditto "${macos_dir}/.build/agent-dist/CardBridgeAgent.app" "${agent_app}"
ditto "${macos_dir}/App/Agent-Info.plist" "${agent_contents}/Info.plist"
mkdir -p "${agent_contents}/Resources"
ditto "${macos_dir}/App/Resources/en.lproj" "${agent_contents}/Resources/en.lproj"
ditto "${macos_dir}/App/Resources/zh-Hans.lproj" "${agent_contents}/Resources/zh-Hans.lproj"
chmod 755 "${contents_dir}/MacOS/CardBridge"
install_name_tool -add_rpath @executable_path/../Frameworks "${contents_dir}/MacOS/CardBridge"

timestamp=${CODE_SIGN_TIMESTAMP:---timestamp=none}
sign_options=()
if [[ "${identity}" != "-" ]]; then
  sign_options=(--options runtime)
fi

# PyInstaller ships extension modules and dylibs beside the helper executable.
# Sign every Mach-O leaf before sealing its helper bundle and the outer app.
while IFS= read -r candidate; do
  if /usr/bin/file -b "${candidate}" | /usr/bin/grep -q 'Mach-O'; then
    codesign --force "${sign_options[@]}" "${timestamp}" --sign "${identity}" "${candidate}"
  fi
done < <(find "${agent_contents}" -type f -print)
codesign --force "${sign_options[@]}" "${timestamp}" --sign "${identity}" "${agent_app}"
# Sparkle contains its updater helper and XPC services. Xcode's normal
# "Code Sign On Copy" behavior is reproduced here for the SwiftPM bundle.
codesign --force --deep "${sign_options[@]}" "${timestamp}" --sign "${identity}" \
  "${contents_dir}/Frameworks/Sparkle.framework"
codesign --force "${sign_options[@]}" "${timestamp}" --sign "${identity}" "${app_dir}"
codesign --verify --deep --strict --verbose=2 "${app_dir}"

echo "Built ${app_dir}"
