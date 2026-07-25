#pragma once

#include <M5Cardputer.h>
#include <WiFiUdp.h>
#include <driver/i2s_std.h>
#include <driver/gpio.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "app_config.h"
#include "pairing.h"

namespace cardbridge {

class AudioTransmitter {
 public:
  explicit AudioTransmitter(PairingManager& pairing) : pairing_(pairing) {}

  bool begin(bool muted);
  // Remote keyboard mode owns the microphone. Keep this separate from the
  // user's persistent mute preference so leaving Remote never clears mute.
  void setActive(bool active);
  void setMuted(bool muted);
  bool active() const { return active_; }
  bool muted() const { return muted_; }
  uint8_t level() const { return level_; }
  uint32_t droppedFrames() const { return droppedFrames_; }
  void dumpRaw() const {
    Serial.print("[raw] L:");
    for (size_t i = 0; i < 16; ++i) Serial.printf(" %04X", (uint16_t)debugStereo_[i * 2]);
    Serial.print("\n[raw] R:");
    for (size_t i = 0; i < 16; ++i) Serial.printf(" %04X", (uint16_t)debugStereo_[i * 2 + 1]);
    Serial.println();
  }
  void printDebug() const {
    Serial.printf(
        "[audio] mic_begin_ok=%u mic_begin_fail=%u captured=%u record_fail=%u "
        "mic_restart=%u sent=%u send_fail=%u udp_restart=%u watchdog=%u "
        "queue_drop=%u level=%u raw_peak=%u\n",
        micBeginOk_, micBeginFail_, captured_, recordFail_, micRestart_, sent_,
        sendFail_, udpRestart_, watchdogRestart_, queueDrop_, level_, rawPeak_);
  }

 private:
  struct AudioFrame {
    uint32_t sequence;
    uint32_t timestampMs;
    int16_t samples[kAudioSamplesPerFrame];
  };

  static void captureTaskEntry(void* argument);
  static void senderTaskEntry(void* argument);
  void captureLoop();
  void senderLoop();
  bool streamingAllowed() const;
  bool micStart();
  void micStop();
  bool udpStart();
  void udpStop();
  void requestPipelineRestart();
  bool sendFrame(const AudioFrame& frame, const IPAddress& ip,
                 const uint8_t token[32]);

  PairingManager& pairing_;
  QueueHandle_t queue_ = nullptr;
  TaskHandle_t captureTask_ = nullptr;
  TaskHandle_t senderTask_ = nullptr;
  i2s_chan_handle_t rxChannel_ = nullptr;
  WiFiUDP udp_;
  volatile bool active_ = false;
  volatile bool muted_ = false;
  volatile bool captureRestartRequested_ = false;
  volatile uint8_t level_ = 0;
  volatile uint16_t rawPeak_ = 0;
  volatile uint32_t droppedFrames_ = 0;
  volatile uint32_t micBeginOk_ = 0;
  volatile uint32_t micBeginFail_ = 0;
  volatile uint32_t captured_ = 0;
  volatile uint32_t recordFail_ = 0;
  volatile uint32_t micRestart_ = 0;
  volatile uint32_t sent_ = 0;
  volatile uint32_t sendFail_ = 0;
  volatile uint32_t udpRestart_ = 0;
  volatile uint32_t watchdogRestart_ = 0;
  volatile uint32_t queueDrop_ = 0;
  volatile int16_t debugStereo_[64] = {};
};

}  // namespace cardbridge
