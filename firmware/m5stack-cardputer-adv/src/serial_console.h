#pragma once

#include <Arduino.h>

#include "audio_tx.h"
#include "models.h"
#include "pairing.h"
#include "settings_store.h"
#include "ui.h"
#include "wifi_mgr.h"

namespace cardbridge {

// Line-based debug console on the USB serial port. Lets the development host
// provision WiFi, drive pairing, and exercise the key/audio pipelines without
// touching the physical keyboard. Physical USB access is the trust boundary.
class SerialConsole {
 public:
  SerialConsole(SettingsStore& store, WifiManager& wifi,
                PairingManager& pairing, AudioTransmitter& audio,
                DeviceUi& ui, DeviceSettings& settings)
      : store_(store), wifi_(wifi), pairing_(pairing), audio_(audio),
        ui_(ui), settings_(settings) {}

  void tick();

 private:
  void handle(const String& line);
  void printStatus();
  void printComputers();

  SettingsStore& store_;
  WifiManager& wifi_;
  PairingManager& pairing_;
  AudioTransmitter& audio_;
  DeviceUi& ui_;
  DeviceSettings& settings_;
  String buffer_;
};

}  // namespace cardbridge
