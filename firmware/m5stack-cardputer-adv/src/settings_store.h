#pragma once

#include <Preferences.h>

#include "app_config.h"
#include "models.h"

namespace cardbridge {

class SettingsStore {
 public:
  bool begin();

  size_t loadWifiNetworks(WifiNetwork* out, size_t capacity);
  bool saveWifiNetworks(const WifiNetwork* networks, size_t count);

  size_t loadPairedMacs(PairedMac* out, size_t capacity);
  bool savePairedMacs(const PairedMac* macs, size_t count);

  DeviceSettings loadSettings();
  bool saveSettings(const DeviceSettings& settings);

 private:
  Preferences preferences_;
  bool ready_ = false;
};

}  // namespace cardbridge
