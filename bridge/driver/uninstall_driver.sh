#!/bin/zsh
set -euo pipefail

installed_bundle=/Library/Audio/Plug-Ins/HAL/CardBridgeMicrophone.driver

sudo rm -rf "${installed_bundle}"
sudo killall coreaudiod

echo "Removed ${installed_bundle}"
