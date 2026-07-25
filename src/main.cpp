#include <M5Cardputer.h>

#include "audio_tx.h"
#include "generated_version.h"
#include "key_tx.h"
#include "pairing.h"
#include "serial_console.h"
#include "settings_store.h"
#include "ui.h"
#include "wifi_mgr.h"

using namespace cardbridge;

namespace {

SettingsStore settingsStore;
DeviceSettings settings;
WifiManager wifi(settingsStore);
PairingManager pairing(settingsStore, wifi);
AudioTransmitter audio(pairing);
KeyTransmitter keys(pairing, settings);
DeviceUi ui(settingsStore, wifi, pairing, audio, keys, settings);
SerialConsole console(settingsStore, wifi, pairing, audio, ui, settings);

void printBootInfo() {
  Serial.println();
  Serial.println("CODEX DECK / Cardputer ADV");
  Serial.printf("Firmware: %s build %lu, protocol %u.%u\n", kFirmwareVersion,
                static_cast<unsigned long>(kFirmwareBuild),
                kDeviceProtocolMajor, kDeviceProtocolMinor);
  Serial.printf("Chip: %s r%d, flash: %u, free heap: %u\n",
                ESP.getChipModel(), ESP.getChipRevision(),
                ESP.getFlashChipSize(), ESP.getFreeHeap());
  Serial.println("Audio: PCM16 mono 16kHz / 20ms, TCP:7788 UDP:7789");
}

}  // namespace

void setup() {
  auto config = M5.config();
  // Audio is owned by AudioTransmitter. Leaving M5Unified's speaker/mic
  // drivers enabled lets them retain the same ES8311 and I2S pins, which can
  // produce a buzz when BtnA stops capture and can prevent a clean restart
  // after a power or WiFi transition.
  config.internal_mic = false;
  config.internal_spk = false;
  M5Cardputer.begin(config, true);
  Serial.begin(115200);
  delay(100);
  printBootInfo();

  if (!settingsStore.begin()) Serial.println("ERROR: NVS initialization failed");
  settings = settingsStore.loadSettings();
  wifi.begin();
  pairing.begin(&settings);
  if (!audio.begin(settings.micMuted)) Serial.println("ERROR: audio tasks failed");
  ui.begin();
}

void loop() {
  M5Cardputer.update();
  console.tick();
  wifi.tick();
  pairing.tick();
  ui.tick();
  keys.tick(ui.consumesKeyboard());
  delay(5);
}
