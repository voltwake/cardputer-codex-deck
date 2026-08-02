#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
source_bundle=${script_dir}/build/CardBridgeMicrophone.driver
install_dir=/Library/Audio/Plug-Ins/HAL
installed_bundle=${install_dir}/CardBridgeMicrophone.driver

if [[ ! -d "${source_bundle}" ]]; then
  echo "Driver is not built. Run bridge/driver/build_driver.sh first." >&2
  exit 1
fi

sudo mkdir -p "${install_dir}"
sudo ditto "${source_bundle}" "${installed_bundle}"
sudo chown -R root:wheel "${installed_bundle}"
sudo find "${installed_bundle}" -type d -exec chmod 755 {} \;
sudo find "${installed_bundle}" -type f -exec chmod 644 {} \;
sudo chmod 755 "${installed_bundle}/Contents/MacOS/CardBridgeMicrophone"
sudo killall coreaudiod

echo "Installed ${installed_bundle}"
