#include "audio_tx.h"

#include <lwip/def.h>
#include <mbedtls/md.h>

#include <cstring>

namespace cardbridge {
namespace {

struct __attribute__((packed)) AudioPacketHeader {
  uint32_t sequence;
  uint32_t timestampMs;
  uint8_t hmac[8];
};

}  // namespace

bool AudioTransmitter::begin(bool muted) {
  muted_ = muted;
  queue_ = xQueueCreate(kAudioRingFrames, sizeof(AudioFrame));
  if (!queue_) return false;
  const BaseType_t captureOk = xTaskCreatePinnedToCore(
      captureTaskEntry, "mic_capture", 4096, this, 3, &captureTask_, 0);
  const BaseType_t senderOk = xTaskCreatePinnedToCore(
      senderTaskEntry, "audio_udp", 4096, this, 2, &senderTask_, 0);
  return captureOk == pdPASS && senderOk == pdPASS;
}

void AudioTransmitter::setActive(bool active) {
  active_ = active;
  if (!active && queue_) {
    xQueueReset(queue_);
    captureRestartRequested_ = false;
  }
}

void AudioTransmitter::setMuted(bool muted) {
  muted_ = muted;
  if (muted && queue_) {
    xQueueReset(queue_);
    captureRestartRequested_ = false;
  }
}

bool AudioTransmitter::streamingAllowed() const {
  if (!active_ || muted_) return false;
  IPAddress ignoredIp;
  uint8_t ignoredToken[32];
  return pairing_.audioEndpoint(ignoredIp, ignoredToken);
}

void AudioTransmitter::captureTaskEntry(void* argument) {
  static_cast<AudioTransmitter*>(argument)->captureLoop();
}

void AudioTransmitter::senderTaskEntry(void* argument) {
  static_cast<AudioTransmitter*>(argument)->senderLoop();
}

// The ADV microphone is driven directly: M5Unified's Mic_Class is broken for
// this board on both Arduino cores (all-zero samples on core 2.x; wrong frame
// pacing plus WiFi starvation on core 3.x — verified on hardware 2026-07-14),
// while the factory demo only works built against native ESP-IDF. We instead
// program the ES8311 ADC over I2C (the I2C path is proven by the speaker) and
// read PCM with the IDF i2s_std driver. ES8311 register sequences mirror
// M5Unified's `_microphone_enabled_cb_cardputer_adv`.
bool AudioTransmitter::micStart() {
  // Working recipe from vc1235-ui/vibe-cardputer (same board, same bug, solved).
  // Three non-obvious requirements, all mandatory:
  //   1. gpio_reset_pin() first — clear M5Unified's residual I2S pin state.
  //   2. MCLK routed to a real unwired pin (GPIO13) — with I2S_GPIO_UNUSED the
  //      IDF 5.x clock tree doesn't fully init and DIN floats high (0xFFFF).
  //   3. Start I2S (BCLK running) BEFORE configuring the ES8311, so its PLL
  //      can lock onto BCLK. 16-bit STEREO slots → BCLK = 512kHz, ES8311
  //      pre_multi x8 → 4.096MHz internal MCLK, /256 → 16kHz.

  gpio_reset_pin(GPIO_NUM_41);
  gpio_reset_pin(GPIO_NUM_43);
  gpio_reset_pin(GPIO_NUM_46);

  i2s_chan_config_t channelConfig =
      I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  channelConfig.auto_clear = true;
  if (i2s_new_channel(&channelConfig, nullptr, &rxChannel_) != ESP_OK) {
    return false;
  }
  i2s_std_config_t standardConfig = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(kAudioSampleRate),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                      I2S_SLOT_MODE_STEREO),
      .gpio_cfg = {
          // MCLK must point at a real GPIO or the IDF clock tree stays half-init
      // and DIN floats (that was the 0xFFFF bug). The pin is never wired to
      // the codec, so it only has to be free: GPIO13 is breakout-header only.
      // NOT GPIO0 — that is BtnA, and driving it wedges the button at
      // "pressed" (I2S does not restore the pad on i2s_del_channel).
      .mclk = GPIO_NUM_13,
          .bclk = GPIO_NUM_41,
          .ws = GPIO_NUM_43,
          .dout = I2S_GPIO_UNUSED,
          .din = GPIO_NUM_46,
          .invert_flags = {},
      },
  };
  if (i2s_channel_init_std_mode(rxChannel_, &standardConfig) != ESP_OK ||
      i2s_channel_enable(rxChannel_) != ESP_OK) {
    i2s_del_channel(rxChannel_);
    rxChannel_ = nullptr;
    return false;
  }
  vTaskDelay(pdMS_TO_TICKS(200));  // let BCLK stabilize before codec PLL lock

  // ES8311 register sequence ported verbatim from the working firmware.
  auto write = [](uint8_t reg, uint8_t value) {
    M5.In_I2C.writeRegister8(0x18, reg, value, 100000);
  };
  write(0x01, 0x30);
  write(0x02, 0x00);
  write(0x03, 0x10);
  write(0x16, 0x24);  // ADC gain
  write(0x04, 0x10);
  write(0x05, 0x00);
  write(0x0B, 0x00);
  write(0x0C, 0x00);
  write(0x10, 0x1F);
  write(0x11, 0x7F);
  write(0x00, 0x80);  // CSM power on, slave mode
  vTaskDelay(pdMS_TO_TICKS(20));
  write(0x01, 0xBF);  // clock source = BCLK, all clocks on
  // Clock coefficients: pre_div=1, pre_multi=x8, lrck_div=256 (BCLK 512k → 16k)
  write(0x02, 0x18);  // (0<<5) | (3<<3): pre_div-1=0, pre_multi=x8
  write(0x05, 0x00);
  write(0x03, 0x10);  // adc_osr
  write(0x04, 0x10);
  write(0x07, 0x00);
  write(0x08, 0xFF);  // lrck_l = 255
  write(0x06, 0x03);  // bclk_div-1
  write(0x09, 0x0C);  // SDP in: Philips, 16-bit
  write(0x0A, 0x0C);  // SDP out: 16-bit, ADC output enabled
  write(0x0D, 0x01);  // power up analog
  write(0x0E, 0x02);
  // This product never plays through the Cardputer speaker. Keep the DAC and
  // headphone driver down while the ADC is running; powering them here was
  // the source of the audible hiss/buzz around BtnA mode changes.
  write(0x12, 0x02);  // power down DAC
  write(0x13, 0x00);  // disable headphone output driver
  write(0x1B, 0x0A);  // HPF
  write(0x1C, 0x6A);  // DC offset cancel
  // Keep the codec at its proven-clean gain. Cranking 0x17/0x16 raised the
  // noise floor and glitch spikes far more than the voice (measured: quiet
  // peak 1 -> 3881 while speech only went 330 -> 2672), i.e. it destroyed SNR.
  // At these values the mic is quiet but clean (~16:1 speech/noise); make-up
  // gain is applied in software on the bridge instead.
  write(0x17, 0xBF);  // ADC digital volume: 0 dB
  write(0x15, 0x40);  // ADC ramp rate
  write(0x14, 0x1A);  // analog MIC, PGA gain
  write(0x37, 0x48);
  write(0x44, 0x08);
  write(0x45, 0x00);
  vTaskDelay(pdMS_TO_TICKS(50));
  return true;
}

void AudioTransmitter::micStop() {
  // Mute the ADC before clocks disappear so the shared codec cannot emit a
  // shutdown transient through any residual analog path.
  M5.In_I2C.writeRegister8(0x18, 0x17, 0x00, 100000);
  M5.In_I2C.writeRegister8(0x18, 0x13, 0x00, 100000);
  vTaskDelay(pdMS_TO_TICKS(5));
  if (rxChannel_) {
    i2s_channel_disable(rxChannel_);
    i2s_del_channel(rxChannel_);
    rxChannel_ = nullptr;
    // i2s_del_channel leaves the pads driven; hand them back so nothing else
    // (e.g. a button on a shared pin) reads a stuck level.
    gpio_reset_pin(GPIO_NUM_13);
    gpio_reset_pin(GPIO_NUM_41);
    gpio_reset_pin(GPIO_NUM_43);
    gpio_reset_pin(GPIO_NUM_46);
  }
  static constexpr uint8_t kDisableSeq[][2] = {
      {0x0D, 0xFC},  // SYSTEM: power down analog circuitry
      {0x0E, 0x6A},
      {0x00, 0x00},  // RESET: CSM power down
  };
  for (const auto& entry : kDisableSeq) {
    M5.In_I2C.writeRegister8(0x18, entry[0], entry[1], 100000);
  }
}

void AudioTransmitter::captureLoop() {
  uint32_t sequence = 0;
  uint8_t consecutiveReadFailures = 0;
  uint16_t consecutiveInvalidFrames = 0;
  for (;;) {
    if (!streamingAllowed()) {
      if (rxChannel_) {
        micStop();
        level_ = 0;
        rawPeak_ = 0;
        xQueueReset(queue_);
      }
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    if (captureRestartRequested_) {
      captureRestartRequested_ = false;
      if (rxChannel_) micStop();
      xQueueReset(queue_);
      ++micRestart_;
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    if (!rxChannel_) {
      if (micStart()) {
        ++micBeginOk_;
      } else {
        ++micBeginFail_;
        vTaskDelay(pdMS_TO_TICKS(1000));
        continue;
      }
    }

    AudioFrame frame{};
    // Read interleaved 16-bit L/R stereo; keep the left slot (ES8311 ADC).
    static int16_t stereo[kAudioSamplesPerFrame * 2];
    size_t received = 0;
    bool readOk = true;
    while (received < sizeof(stereo)) {
      size_t bytesRead = 0;
      const esp_err_t result = i2s_channel_read(
          rxChannel_, reinterpret_cast<uint8_t*>(stereo) + received,
          sizeof(stereo) - received, &bytesRead, pdMS_TO_TICKS(200));
      if (result != ESP_OK || bytesRead == 0) {
        readOk = false;
        break;
      }
      received += bytesRead;
    }
    if (!readOk) {
      ++recordFail_;
      if (++consecutiveReadFailures >= kAudioReadFailureRestartCount) {
        micStop();
        xQueueReset(queue_);
        ++micRestart_;
        consecutiveReadFailures = 0;
        vTaskDelay(pdMS_TO_TICKS(250));
      }
      continue;
    }
    consecutiveReadFailures = 0;
    frame.sequence = sequence++;
    frame.timestampMs = millis();
    for (size_t i = 0; i < kAudioSamplesPerFrame; ++i) {
      frame.samples[i] = stereo[i * 2];
    }
    for (size_t i = 0; i < 64; ++i) debugStereo_[i] = stereo[i];
    ++captured_;
    if (!streamingAllowed()) continue;

    uint16_t peak = 0;
    bool constantFrame = true;
    for (size_t i = 0; i < kAudioSamplesPerFrame; ++i) {
      int32_t sample = frame.samples[i];
      if (i && frame.samples[i] != frame.samples[0]) constantFrame = false;
      const uint16_t absolute = static_cast<uint16_t>(
          sample < 0 ? min<int32_t>(-sample, 32767) : sample);
      if (absolute > peak) peak = absolute;
    }
    rawPeak_ = peak;
    level_ = static_cast<uint8_t>(min<uint32_t>(255, peak >> 7));

    // A powered-down or unlocked ES8311 commonly returns a perfectly constant
    // 0x0000/0xFFFF/DC frame while I2S still reports successful reads. Real
    // microphone input always has at least converter noise. Restart instead
    // of streaming a permanent buzz or silent DC forever.
    if (constantFrame) {
      if (++consecutiveInvalidFrames >= kAudioInvalidFrameRestartCount) {
        micStop();
        xQueueReset(queue_);
        ++micRestart_;
        consecutiveInvalidFrames = 0;
        vTaskDelay(pdMS_TO_TICKS(250));
      }
      continue;
    }
    consecutiveInvalidFrames = 0;

    if (xQueueSend(queue_, &frame, 0) != pdPASS) {
      AudioFrame discarded;
      xQueueReceive(queue_, &discarded, 0);
      xQueueSend(queue_, &frame, 0);
      ++droppedFrames_;
      ++queueDrop_;
    }
  }
}

bool AudioTransmitter::udpStart() {
  udp_.stop();
  return udp_.begin(0) == 1;
}

void AudioTransmitter::udpStop() {
  udp_.stop();
}

void AudioTransmitter::requestPipelineRestart() {
  captureRestartRequested_ = true;
  if (queue_) xQueueReset(queue_);
}

void AudioTransmitter::senderLoop() {
  AudioFrame frame;
  bool udpReady = false;
  uint8_t consecutiveSendFailures = 0;
  bool ackInitialized = false;
  uint32_t lastAckReceived = 0;
  uint32_t lastAckProgressMs = 0;
  uint32_t sentAtAckProgress = 0;
  for (;;) {
    IPAddress ip;
    uint8_t token[32];
    if (!active_ || muted_ || !pairing_.audioEndpoint(ip, token)) {
      if (udpReady) {
        udpStop();
        udpReady = false;
      }
      ackInitialized = false;
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    if (!udpReady) {
      if (!udpStart()) {
        ++sendFail_;
        vTaskDelay(pdMS_TO_TICKS(500));
        continue;
      }
      udpReady = true;
      consecutiveSendFailures = 0;
    }
    if (xQueueReceive(queue_, &frame, pdMS_TO_TICKS(100)) != pdPASS) continue;
    if (!active_ || muted_ || !pairing_.audioEndpoint(ip, token)) continue;
    if (sendFrame(frame, ip, token)) {
      ++sent_;
      consecutiveSendFailures = 0;
    } else {
      ++droppedFrames_;
      ++sendFail_;
      if (++consecutiveSendFailures >= kAudioSendFailureRestartCount) {
        udpStop();
        udpReady = false;
        ++udpRestart_;
        requestPipelineRestart();
        consecutiveSendFailures = 0;
      }
    }

    uint32_t ackReceived = 0;
    uint32_t ackUpdatedMs = 0;
    bool outputReady = false;
    const uint32_t now = millis();
    if (pairing_.audioStatus(ackReceived, ackUpdatedMs, outputReady) &&
        now - ackUpdatedMs <= kAudioAckFreshMs) {
      if (!ackInitialized || ackReceived != lastAckReceived) {
        ackInitialized = true;
        lastAckReceived = ackReceived;
        lastAckProgressMs = now;
        sentAtAckProgress = sent_;
      } else if (outputReady && now - lastAckProgressMs >= kAudioAckStallMs &&
                 sent_ - sentAtAckProgress >= kAudioAckMinSentFrames) {
        // TCP is healthy enough to deliver status, but the Mac has stopped
        // receiving UDP. Recreate both the UDP socket and the capture clock so
        // a power/WiFi transition cannot leave a false-online audio path.
        udpStop();
        udpReady = false;
        ++udpRestart_;
        ++watchdogRestart_;
        requestPipelineRestart();
        lastAckProgressMs = now;
        sentAtAckProgress = sent_;
      }
    }
  }
}

bool AudioTransmitter::sendFrame(const AudioFrame& frame, const IPAddress& ip,
                                 const uint8_t token[32]) {
  AudioPacketHeader header{};
  header.sequence = htonl(frame.sequence);
  header.timestampMs = htonl(frame.timestampMs);

  uint8_t digest[32];
  mbedtls_md_context_t context;
  mbedtls_md_init(&context);
  const mbedtls_md_info_t* info =
      mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  bool ok = info && mbedtls_md_setup(&context, info, 1) == 0 &&
            mbedtls_md_hmac_starts(&context, token, 32) == 0 &&
            mbedtls_md_hmac_update(
                &context, reinterpret_cast<const uint8_t*>(&header), 8) == 0 &&
            mbedtls_md_hmac_update(
                &context, reinterpret_cast<const uint8_t*>(frame.samples),
                kAudioPayloadBytes) == 0 &&
            mbedtls_md_hmac_finish(&context, digest) == 0;
  mbedtls_md_free(&context);
  if (!ok) return false;
  memcpy(header.hmac, digest, sizeof(header.hmac));

  if (!udp_.beginPacket(ip, kAudioPort)) return false;
  udp_.write(reinterpret_cast<const uint8_t*>(&header), sizeof(header));
  udp_.write(reinterpret_cast<const uint8_t*>(frame.samples), kAudioPayloadBytes);
  return udp_.endPacket() == 1;
}

}  // namespace cardbridge
