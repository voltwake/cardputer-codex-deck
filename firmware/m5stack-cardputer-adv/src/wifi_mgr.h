#pragma once

#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "app_config.h"
#include "models.h"
#include "settings_store.h"

namespace cardbridge {

class WifiManager {
 public:
  explicit WifiManager(SettingsStore& store) : store_(store) {}

  void begin();
  void tick();
  void startScan();
  bool connectSaved(size_t index);
  bool addAndConnect(const String& ssid, const String& password);
  bool forget(const String& ssid);

  bool connected() const { return WiFi.status() == WL_CONNECTED; }
  bool scanning() const { return scanning_ || pendingScan_; }
  bool needsSetup() const { return needsSetup_; }
  void acknowledgeSetup() { needsSetup_ = false; }
  String currentSsid() const { return connected() ? WiFi.SSID() : String(); }
  int32_t rssi() const { return connected() ? WiFi.RSSI() : -127; }
  IPAddress localIp() const { return WiFi.localIP(); }

  size_t savedCount() const { return savedCount_; }
  const WifiNetwork& saved(size_t index) const { return saved_[index]; }
  bool isSaved(const String& ssid) const;

  size_t scanCount() const { return scanCount_; }
  const WifiScanResult& scanResult(size_t index) const { return scan_[index]; }

 private:
  static void scanTaskEntry(void* argument);
  void tryKnownNetworks();
  bool startConnection(size_t index);
  void runPendingScan();
  void pollScanResult();
  void collectResults(int16_t result);
  int savedIndex(const String& ssid) const;

  SettingsStore& store_;
  WifiNetwork saved_[kMaxWifiNetworks];
  WifiScanResult scan_[kMaxWifiNetworks * 2];
  size_t savedCount_ = 0;
  size_t scanCount_ = 0;
  bool scanning_ = false;
  bool pendingScan_ = false;
  QueueHandle_t scanResultQueue_ = nullptr;
  bool needsSetup_ = false;
  uint32_t lastScanStartMs_ = 0;
  bool scanEverSucceeded_ = false;
  uint32_t connectStartedMs_ = 0;
  uint32_t lastReconnectMs_ = 0;
  size_t reconnectIndex_ = 0;
  size_t reconnectAttempts_ = 0;
};

}  // namespace cardbridge
