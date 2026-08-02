#include "wifi_mgr.h"

#include <algorithm>

namespace cardbridge {

void WifiManager::begin() {
  savedCount_ = store_.loadWifiNetworks(saved_, kMaxWifiNetworks);
  scanResultQueue_ = xQueueCreate(1, sizeof(int16_t));
  if (!scanResultQueue_) Serial.println("[wifi] failed to create scan result queue");
  WiFi.mode(WIFI_STA);
  // MIN_MODEM keeps the association alive and wakes for each DTIM beacon.
  // Continuous microphone traffic naturally keeps the radio awake in Remote
  // mode, while Local/idle use can spend most beacon intervals asleep.
  if (!WiFi.setSleep(WIFI_PS_MIN_MODEM)) {
    Serial.println("[wifi] modem sleep unavailable");
  }
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);  // Credentials live in our own multi-network NVS list.
  if (savedCount_ > 0) {
    tryKnownNetworks();
  } else {
    needsSetup_ = true;
    startScan();
  }
}

void WifiManager::tick() {
  pollScanResult();
  if (pendingScan_ && !scanning_) runPendingScan();

  // The boot-time scan can run before the STA interface is fully up and come
  // back empty. Keep retrying while we have never seen a network.
  if (!pendingScan_ && !scanEverSucceeded_ && !connected() &&
      connectStartedMs_ == 0 &&
      millis() - lastScanStartMs_ >= 4000) {
    startScan();
  }

  if (connected()) {
    connectStartedMs_ = 0;
    return;
  }

  // The radio scan runs on a low-priority worker. Do not start or tear down a
  // station connection underneath it; the main loop remains free to scan keys
  // and draw the UI while the worker waits for the WiFi driver.
  if (scanning_) return;

  const uint32_t now = millis();
  if (connectStartedMs_ && now - connectStartedMs_ > 12000) {
    WiFi.disconnect();
    connectStartedMs_ = 0;
    ++reconnectAttempts_;
    if (reconnectAttempts_ < savedCount_) {
      reconnectIndex_ = (reconnectIndex_ + 1) % savedCount_;
      startConnection(reconnectIndex_);
    } else {
      reconnectIndex_ = 0;
      needsSetup_ = true;
      if (!scanning_) startScan();
    }
  } else if (!connectStartedMs_ && savedCount_ > 0 &&
             now - lastReconnectMs_ > 10000 && !scanning_) {
    lastReconnectMs_ = now;
    tryKnownNetworks();
  }
}

// The Arduino async scan API is unreliable on this core (scanComplete() reports
// "done, 0 networks" instantly, sometimes -2). Keep the reliable synchronous
// driver call, but run it on core 0 at low priority so its 2-4 second wait never
// stalls keyboard sampling or rendering on the Arduino loop task.
void WifiManager::startScan() {
  if (pendingScan_ || scanning_) return;
  scanCount_ = 0;
  pendingScan_ = true;
}

void WifiManager::runPendingScan() {
  pendingScan_ = false;
  if (!scanResultQueue_) {
    Serial.println("[wifi] scan unavailable: no result queue");
    return;
  }
  scanning_ = true;
  WiFi.scanDelete();
  lastScanStartMs_ = millis();
  if (xTaskCreatePinnedToCore(scanTaskEntry, "wifi_scan", 4096, this, 1,
                              nullptr, 0) != pdPASS) {
    scanning_ = false;
    Serial.println("[wifi] failed to start scan worker");
  }
}

void WifiManager::scanTaskEntry(void* argument) {
  auto* manager = static_cast<WifiManager*>(argument);
  const int16_t result = WiFi.scanNetworks(false, false);
  xQueueOverwrite(manager->scanResultQueue_, &result);
  vTaskDelete(nullptr);
}

void WifiManager::pollScanResult() {
  if (!scanning_ || !scanResultQueue_) return;
  int16_t result = WIFI_SCAN_FAILED;
  if (xQueueReceive(scanResultQueue_, &result, 0) != pdPASS) return;
  scanning_ = false;
  Serial.printf("[wifi] worker scan result: %d\n", result);
  collectResults(result);
}

void WifiManager::collectResults(int16_t result) {
  if (result > 0) scanEverSucceeded_ = true;

  const size_t capacity = sizeof(scan_) / sizeof(scan_[0]);
  scanCount_ = 0;
  for (int i = 0; i < max<int16_t>(result, 0) && scanCount_ < capacity; ++i) {
    const String ssid = WiFi.SSID(i);
    if (ssid.isEmpty()) continue;
    bool duplicate = false;
    for (size_t j = 0; j < scanCount_; ++j) {
      if (scan_[j].ssid == ssid) {
        if (WiFi.RSSI(i) > scan_[j].rssi) scan_[j].rssi = WiFi.RSSI(i);
        duplicate = true;
        break;
      }
    }
    if (duplicate) continue;
    scan_[scanCount_].ssid = ssid;
    scan_[scanCount_].rssi = WiFi.RSSI(i);
    scan_[scanCount_].encrypted = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
    scan_[scanCount_].saved = isSaved(ssid);
    ++scanCount_;
  }

  // Saved networks remain manageable even when they are currently offline or
  // outside scan range. This also makes the current connection explicit.
  for (size_t i = 0; i < savedCount_ && scanCount_ < capacity; ++i) {
    bool present = false;
    for (size_t j = 0; j < scanCount_; ++j) {
      if (scan_[j].ssid == saved_[i].ssid) {
        present = true;
        break;
      }
    }
    if (present) continue;
    scan_[scanCount_].ssid = saved_[i].ssid;
    scan_[scanCount_].rssi = connected() && WiFi.SSID() == saved_[i].ssid
                                ? WiFi.RSSI() : -127;
    scan_[scanCount_].encrypted = !saved_[i].password.isEmpty();
    scan_[scanCount_].saved = true;
    ++scanCount_;
  }
  std::sort(scan_, scan_ + scanCount_, [](const WifiScanResult& a,
                                          const WifiScanResult& b) {
    return a.rssi > b.rssi;
  });
  WiFi.scanDelete();
}

void WifiManager::tryKnownNetworks() {
  if (savedCount_ == 0) return;

  // If scan data is available, put the strongest known network first.
  size_t best = 0;
  int32_t bestRssi = -128;
  for (size_t i = 0; i < scanCount_; ++i) {
    const int idx = savedIndex(scan_[i].ssid);
    if (idx >= 0 && scan_[i].rssi > bestRssi) {
      best = static_cast<size_t>(idx);
      bestRssi = scan_[i].rssi;
    }
  }
  reconnectIndex_ = best;
  reconnectAttempts_ = 0;
  connectSaved(best);
}

bool WifiManager::connectSaved(size_t index) {
  if (index >= savedCount_) return false;
  reconnectIndex_ = index;
  reconnectAttempts_ = 0;
  return startConnection(index);
}

bool WifiManager::startConnection(size_t index) {
  WiFi.disconnect();
  WiFi.begin(saved_[index].ssid.c_str(), saved_[index].password.c_str());
  connectStartedMs_ = millis();
  needsSetup_ = false;
  return true;
}

bool WifiManager::addAndConnect(const String& ssid, const String& password) {
  int index = savedIndex(ssid);
  if (index < 0) {
    if (savedCount_ >= kMaxWifiNetworks) return false;
    index = static_cast<int>(savedCount_++);
  }
  saved_[index].ssid = ssid;
  saved_[index].password = password;
  store_.saveWifiNetworks(saved_, savedCount_);
  return connectSaved(static_cast<size_t>(index));
}

bool WifiManager::forget(const String& ssid) {
  const int index = savedIndex(ssid);
  if (index < 0) return false;
  const bool wasCurrent = connected() && WiFi.SSID() == ssid;
  for (size_t i = static_cast<size_t>(index); i + 1 < savedCount_; ++i) {
    saved_[i] = saved_[i + 1];
  }
  --savedCount_;
  store_.saveWifiNetworks(saved_, savedCount_);
  for (size_t i = 0; i < scanCount_; ++i) {
    if (scan_[i].ssid == ssid) scan_[i].saved = false;
  }
  if (wasCurrent) WiFi.disconnect();
  if (savedCount_ == 0) {
    needsSetup_ = true;
    startScan();
  }
  return true;
}

int WifiManager::savedIndex(const String& ssid) const {
  for (size_t i = 0; i < savedCount_; ++i) {
    if (saved_[i].ssid == ssid) return static_cast<int>(i);
  }
  return -1;
}

bool WifiManager::isSaved(const String& ssid) const {
  return savedIndex(ssid) >= 0;
}

}  // namespace cardbridge
