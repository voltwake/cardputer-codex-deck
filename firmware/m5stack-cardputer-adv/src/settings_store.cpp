#include "settings_store.h"

namespace cardbridge {
namespace {

String keyFor(const char* prefix, size_t index) {
  return String(prefix) + String(index);
}

}  // namespace

bool SettingsStore::begin() {
  ready_ = preferences_.begin("cardbridge", false);
  return ready_;
}

size_t SettingsStore::loadWifiNetworks(WifiNetwork* out, size_t capacity) {
  if (!ready_) return 0;
  const size_t count = min<size_t>(preferences_.getUChar("wifi_n", 0), capacity);
  for (size_t i = 0; i < count; ++i) {
    out[i].ssid = preferences_.getString(keyFor("ws", i).c_str(), "");
    out[i].password = preferences_.getString(keyFor("wp", i).c_str(), "");
  }
  return count;
}

bool SettingsStore::saveWifiNetworks(const WifiNetwork* networks, size_t count) {
  if (!ready_ || count > kMaxWifiNetworks) return false;
  const size_t previous = preferences_.getUChar("wifi_n", 0);
  preferences_.putUChar("wifi_n", static_cast<uint8_t>(count));
  for (size_t i = 0; i < count; ++i) {
    preferences_.putString(keyFor("ws", i).c_str(), networks[i].ssid);
    preferences_.putString(keyFor("wp", i).c_str(), networks[i].password);
  }
  for (size_t i = count; i < previous; ++i) {
    preferences_.remove(keyFor("ws", i).c_str());
    preferences_.remove(keyFor("wp", i).c_str());
  }
  return true;
}

size_t SettingsStore::loadPairedMacs(PairedMac* out, size_t capacity) {
  if (!ready_) return 0;
  const size_t count = min<size_t>(preferences_.getUChar("mac_n", 0), capacity);
  for (size_t i = 0; i < count; ++i) {
    out[i].id = preferences_.getString(keyFor("mi", i).c_str(), "");
    out[i].name = preferences_.getString(keyFor("mn", i).c_str(), "Mac");
    out[i].token = preferences_.getString(keyFor("mt", i).c_str(), "");
  }
  return count;
}

bool SettingsStore::savePairedMacs(const PairedMac* macs, size_t count) {
  if (!ready_ || count > kMaxPairedMacs) return false;
  const size_t previous = preferences_.getUChar("mac_n", 0);
  preferences_.putUChar("mac_n", static_cast<uint8_t>(count));
  for (size_t i = 0; i < count; ++i) {
    preferences_.putString(keyFor("mi", i).c_str(), macs[i].id);
    preferences_.putString(keyFor("mn", i).c_str(), macs[i].name);
    preferences_.putString(keyFor("mt", i).c_str(), macs[i].token);
  }
  for (size_t i = count; i < previous; ++i) {
    preferences_.remove(keyFor("mi", i).c_str());
    preferences_.remove(keyFor("mn", i).c_str());
    preferences_.remove(keyFor("mt", i).c_str());
  }
  return true;
}

DeviceSettings SettingsStore::loadSettings() {
  DeviceSettings settings;
  if (!ready_) return settings;
  settings.micMuted = preferences_.getBool("mic_mute", false);
  settings.typelessFunctionKey = preferences_.getUChar("voice_f", 13);
  if (settings.typelessFunctionKey < 13 || settings.typelessFunctionKey > 16) {
    settings.typelessFunctionKey = 13;
  }
  settings.brightness = preferences_.getUChar("bright", kDefaultBrightness);
  settings.screenTimeoutSec =
      preferences_.getUShort("screen_s", kDefaultScreenTimeoutSec);
  settings.lastMacId = preferences_.getString("last_mac", "");
  return settings;
}

bool SettingsStore::saveSettings(const DeviceSettings& settings) {
  if (!ready_) return false;
  preferences_.putBool("mic_mute", settings.micMuted);
  preferences_.putUChar("voice_f", settings.typelessFunctionKey);
  preferences_.putUChar("bright", settings.brightness);
  preferences_.putUShort("screen_s", settings.screenTimeoutSec);
  preferences_.putString("last_mac", settings.lastMacId);
  return true;
}

}  // namespace cardbridge
