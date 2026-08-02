#include "ui.h"

#include <USB.h>

#include "ui_background_asset.h"
#include "ui_font_data.h"

namespace cardbridge {
namespace {

constexpr int kWidth = 240;
constexpr int kHeight = 135;
constexpr int kStatusHeight = 20;
constexpr uint16_t kBackground = 0x0841;   // near-black blue
constexpr uint16_t kPanel = 0x18E3;        // card body
constexpr uint16_t kPanelDeep = 0x08A2;    // recessed stage / card footer
constexpr uint16_t kPanelSelected = 0x0339;
constexpr uint16_t kLine = 0x2A2C;         // quiet structural line
constexpr uint16_t kAccent = 0x05FF;       // cyan
constexpr uint16_t kAccentWarm = 0xFD20;   // orange
constexpr uint16_t kTextDim = 0x8410;
constexpr uint16_t kGood = 0x07E9;
constexpr uint16_t kBad = 0xF9E7;
constexpr int kCodexMargin = 4;
constexpr int kCodexGap = 4;
constexpr int kCodexLeftX = kCodexMargin;
constexpr int kCodexColumnWidth = 114;
constexpr int kCodexRightX = kCodexLeftX + kCodexColumnWidth + kCodexGap;
constexpr int kCodexPanelY = 4;
constexpr int kCodexPanelHeight = 127;
constexpr int kCodexPetX = 6;
constexpr int kCodexPetY = 10;
constexpr int kCodexPetSize = 100;
constexpr int kCodexKeyboardX = 6;
constexpr int kCodexKeyboardY = 6;
constexpr int kCodexSessionBadgeWidth = 24;
constexpr int kCodexSessionBadgeHeight = 12;
constexpr int kCodexSessionBadgeX =
    kCodexLeftX + (kCodexColumnWidth - kCodexSessionBadgeWidth) / 2;
constexpr int kCodexSessionBadgeY = 6;
constexpr int kCodexContentX = kCodexRightX + 4;
constexpr int kCodexContentWidth = kCodexColumnWidth - 8;
constexpr int kCodexTitleY = 8;
constexpr int kCodexTitleHeight = 18;
constexpr int kCodexActivityY = 29;
constexpr int kCodexActivityHeight = 70;
constexpr int kCodexActivityLines = 4;
// This is a native 13px face, not a fractionally scaled 15px font. Native
// advances avoid per-character rounding that made CJK spacing look cramped.
// A 17px pitch leaves four real pixels between activity lines.
constexpr float kCodexActivityTextScale = 1.0f;
constexpr int kCodexActivityTextPixels = 13;
constexpr int kCodexActivityTextInsetY = 3;
constexpr int kCodexActivityLinePitch = 17;
constexpr int kCodexWeeklyY = 103;
constexpr int kCodexFiveHourY = 116;
constexpr int kCodexQuotaRowHeight = 10;
constexpr uint8_t kBrightnessLevels[] = {64, 128, 192, 255};
constexpr uint16_t kScreenTimeouts[] = {30, 60, 120, 300, 0};
constexpr uint32_t kInteractiveRenderMs = 100;
constexpr uint32_t kAnimatedRenderMs = 200;
constexpr uint32_t kDimmedAnimatedRenderMs = 500;
constexpr uint32_t kStaticRenderMs = 1000;
constexpr uint32_t kInteractiveWindowMs = 5000;
constexpr uint32_t kIdleDimAfterMs = 15000;
constexpr uint8_t kIdleDimMaxBrightness = 40;
constexpr uint8_t kIdleDimMinBrightness = 12;
constexpr uint32_t kBatterySampleMs = 2000;
constexpr uint32_t kScreenOffBatterySampleMs = 10000;
constexpr uint32_t kBatteryTrendMinMs = 6000;
constexpr uint32_t kBatteryTrendWindowMs = 20000;
constexpr int16_t kChargingRiseMv = 25;
constexpr int16_t kDischargingFallMv = 12;
constexpr uint32_t kInferredChargingHoldMs = 60000;

static_assert(kCodexLeftX == kCodexMargin);
static_assert(kCodexRightX + kCodexColumnWidth + kCodexMargin == kWidth);
static_assert(kCodexPanelY + kCodexPanelHeight + kCodexMargin == kHeight);
static_assert(kCodexPetX >= 0 && kCodexPetX + kCodexPetSize <= kCodexRightX);
static_assert(kCodexPetY >= 0 && kCodexPetY + kCodexPetSize <= kHeight);
static_assert(kCodexContentX + kCodexContentWidth <=
              kCodexRightX + kCodexColumnWidth);
static_assert(kCodexTitleY + kCodexTitleHeight <= kCodexActivityY);
static_assert(kCodexActivityY + kCodexActivityHeight <= kCodexWeeklyY);
static_assert(kCodexActivityTextInsetY +
                  (kCodexActivityLines - 1) * kCodexActivityLinePitch +
                  kCodexActivityTextPixels <=
              kCodexActivityHeight);
static_assert(kCodexWeeklyY + kCodexQuotaRowHeight <= kCodexFiveHourY);
static_assert(kCodexFiveHourY + kCodexQuotaRowHeight <=
              kCodexPanelY + kCodexPanelHeight);
static_assert(ui_background_asset::kWidth == kWidth);
static_assert(ui_background_asset::kHeight == kHeight);

size_t brightnessLevelIndex(uint8_t value) {
  for (size_t i = 0; i < sizeof(kBrightnessLevels); ++i) {
    if (kBrightnessLevels[i] == value) return i;
  }
  return 1;
}

int batteryPercentFromVoltage(int millivolts) {
  // Match M5Unified's ADC-backed Cardputer curve, but apply it to our
  // smoothed voltage so the number does not jump on every LCD refresh.
  const int level = (millivolts - 3300) * 100 / 800;
  return max(0, min(100, level));
}

bool deadlinePending(uint32_t deadline, uint32_t now) {
  return deadline != 0 && static_cast<int32_t>(deadline - now) > 0;
}

size_t utf8CharacterLength(const String& value, size_t index) {
  if (index >= value.length()) return 0;
  const uint8_t lead = static_cast<uint8_t>(value[index]);
  if ((lead & 0x80) == 0) return 1;
  const size_t remaining = value.length() - index;
  if ((lead & 0xE0) == 0xC0) return remaining < 2 ? remaining : 2;
  if ((lead & 0xF0) == 0xE0) return remaining < 3 ? remaining : 3;
  if ((lead & 0xF8) == 0xF0) return remaining < 4 ? remaining : 4;
  return 1;
}

bool asciiOnly(const String& value) {
  for (size_t i = 0; i < value.length(); ++i) {
    if (static_cast<uint8_t>(value[i]) >= 0x80) return false;
  }
  return true;
}

void removeLastUtf8Character(String& value) {
  if (value.isEmpty()) return;
  size_t index = value.length() - 1;
  while (index > 0 &&
         (static_cast<uint8_t>(value[index]) & 0xC0) == 0x80) {
    --index;
  }
  value.remove(index);
}

uint16_t blendRgb565(uint16_t from, uint16_t to, uint8_t amount) {
  const uint16_t inverse = 255 - amount;
  const uint16_t red = (((from >> 11) & 0x1F) * inverse +
                        ((to >> 11) & 0x1F) * amount) /
                       255;
  const uint16_t green = (((from >> 5) & 0x3F) * inverse +
                          ((to >> 5) & 0x3F) * amount) /
                         255;
  const uint16_t blue = ((from & 0x1F) * inverse + (to & 0x1F) * amount) /
                        255;
  return static_cast<uint16_t>((red << 11) | (green << 5) | blue);
}

size_t screenTimeoutIndex(uint16_t value) {
  for (size_t i = 0; i < sizeof(kScreenTimeouts) / sizeof(kScreenTimeouts[0]); ++i) {
    if (kScreenTimeouts[i] == value) return i;
  }
  return 1;
}

}  // namespace

void DeviceUi::begin() {
  auto& display = M5Cardputer.Display;
  display.setRotation(1);
  display.setBrightness(settings_.brightness);
  canvas_.setColorDepth(16);
  void* buffer = canvas_.createSprite(kWidth, kHeight);
  if (!buffer) {
    // Not enough contiguous heap for 16-bit: fall back to 8-bit (half size).
    canvas_.setColorDepth(8);
    buffer = canvas_.createSprite(kWidth, kHeight);
  }
  Serial.printf("[ui] canvas=%p depth=%d heap=%u\n", buffer,
                canvas_.getColorDepth(), ESP.getFreeHeap());
  uiFontData_.set(ui_font_data::kData, ui_font_data::size());
  if (uiFont_.loadFont(&uiFontData_)) {
    uiFontFace_ = &uiFont_;
    Serial.printf("[ui] smooth font=%u glyphs bytes=%u heap=%u\n",
                  ui_font_data::kGlyphCount,
                  static_cast<unsigned>(ui_font_data::size()), ESP.getFreeHeap());
  } else {
    uiFontFace_ = &fonts::efontCN_14;
    Serial.println("[ui] smooth font load failed; using efontCN_14");
  }
  canvas_.setTextFont(1);
  lastActivityMs_ = millis();
  // Boot always lands in Local mode, so the microphone stays physically off
  // until the user explicitly enables keyboard forwarding.
  audio_.setActive(mode_ == UiMode::Remote);
  updateBatteryState(true);
  render();
  lastRenderMs_ = millis();
  renderRequested_ = false;
}

void DeviceUi::setMode(UiMode mode) {
  if (mode_ == mode) return;
  mode_ = mode;
  audio_.setActive(mode_ == UiMode::Remote);
  resetBatteryTrend();
  renderRequested_ = true;
  Serial.printf("[ui] mode=%s mic_active=%d muted=%d\n", modeName(),
                audio_.active(), audio_.muted());
  suppressUntilRelease_ = M5Cardputer.Keyboard.isPressed();
}

void DeviceUi::showCodex() {
  lastAgentFocusId_.clear();
  lastAgentFocusSeq_ = 0;
  selectedAgentId_.clear();
  setPage(Page::Codex);
}

void DeviceUi::tick() {
  // The mode is the user's decision alone: connecting/disconnecting never
  // changes it. Auto-entering Remote on connect stole the device out of the
  // user's hands; a live link only means keys *can* be sent, not that they
  // should be. Boot lands in Local; only BtnA leaves it.

  // BtnA: the dedicated physical mode switch (wakes the screen first).
  if (M5Cardputer.BtnA.wasClicked()) {
    Serial.println("[ui] BtnA click");
    noteActivity();
    if (screenOff_) {
      wakeScreen();
    } else {
      toggleMode();
    }
  }

  if (suppressUntilRelease_ && !M5Cardputer.Keyboard.isPressed()) {
    suppressUntilRelease_ = false;
  }

  if (M5Cardputer.Keyboard.isPressed()) {
    noteActivity();
    if (screenOff_) {
      wakeScreen();
      // In Local mode the waking keypress must not also act on the UI.
      // In Remote mode keys keep flowing to the Mac uninterrupted.
      if (mode_ == UiMode::Local) suppressUntilRelease_ = true;
    }
  }
  updateBatteryState();
  updateScreenPower();

  const uint32_t agentSnapshotSeq = pairing_.agentSeq();
  const LinkState linkState = pairing_.state();
  const bool wifiConnected = wifi_.connected();
  if (agentSnapshotSeq != lastAgentSnapshotSeq_ ||
      linkState != lastLinkState_ || wifiConnected != lastWifiConnected_) {
    lastAgentSnapshotSeq_ = agentSnapshotSeq;
    lastLinkState_ = linkState;
    lastWifiConnected_ = wifiConnected;
    renderRequested_ = true;
  }

  // First-boot funnel: no WiFi credentials -> jump into setup.
  if (wifi_.needsSetup() && mode_ == UiMode::Local && page_ == Page::Main) {
    wifi_.acknowledgeSetup();
    wifi_.startScan();
    setPage(Page::Wifi);
  }
  // Pairing flow interrupts (they require typing, so force Local).
  if (pairing_.pairCodeRequested() && page_ != Page::PairCode) {
    setMode(UiMode::Local);
    textEntry_.clear();
    setPage(Page::PairCode);
  } else if (page_ == Page::PairCode && pairing_.connected()) {
    setPage(Page::Computers);
  }

  if (mode_ == UiMode::Local &&
      (page_ == Page::Computers || page_ == Page::AddComputer) &&
      millis() - lastComputerScanMs_ >= 10000) {
    pairing_.requestDiscovery();
    lastComputerScanMs_ = millis();
  }

  // A new user prompt moves the pet to that session. Manual left/right
  // selection remains sticky until another prompt changes focus again.
  const bool showingCodex = page_ == Page::Main || page_ == Page::Codex;
  if (showingCodex &&
      (pairing_.agentFocusId() != lastAgentFocusId_ ||
       pairing_.agentFocusSeq() != lastAgentFocusSeq_)) {
    lastAgentFocusId_ = pairing_.agentFocusId();
    lastAgentFocusSeq_ = pairing_.agentFocusSeq();
    selectedAgentId_ = lastAgentFocusId_;
    renderRequested_ = true;
  }
  if (showingCodex && !selectedAgentId_.isEmpty()) {
    bool found = false;
    for (size_t i = 0; i < pairing_.agentCount(); ++i) {
      if (pairing_.agent(i).id == selectedAgentId_) {
        agentSelection_ = i;
        found = true;
        break;
      }
    }
    if (!found) {
      if (pairing_.agentCount()) {
        agentSelection_ = min(agentSelection_, pairing_.agentCount() - 1);
        selectedAgentId_ = pairing_.agent(agentSelection_).id;
      } else {
        agentSelection_ = 0;
        selectedAgentId_.clear();
      }
    }
  }

  // Input routing.
  consumesKeyboard_ = mode_ == UiMode::Local || suppressUntilRelease_;
  if (mode_ == UiMode::Local && !suppressUntilRelease_ &&
      M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
    noteActivity();
    handleInput();
    renderRequested_ = true;
  }

  // Interactive input stays at 10 fps. Once untouched, animated Codex states
  // use 5 fps (2 fps while dimmed) and static screens use 1 fps. This avoids
  // pushing the complete 240x135 sprite over SPI ten times a second forever.
  const uint32_t now = millis();
  if (!screenOff_ &&
      (renderRequested_ || now - lastRenderMs_ >= renderIntervalMs())) {
    render();
    lastRenderMs_ = now;
    renderRequested_ = false;
  }
}

// ---------------------------------------------------------------- input --

bool DeviceUi::pressed(char character) const {
  const auto& state = M5Cardputer.Keyboard.keysState();
  for (char c : state.word) {
    if (tolower(static_cast<unsigned char>(c)) ==
        tolower(static_cast<unsigned char>(character))) return true;
  }
  return false;
}

// Arrow legends on the Cardputer keycaps: ; up  . down  , left  / right.
// ijkl kept as an alternative for one-handed use.
bool DeviceUi::navUp() const { return pressed(';') || pressed('i'); }
bool DeviceUi::navDown() const { return pressed('.') || pressed('k'); }
bool DeviceUi::navLeft() const { return pressed(',') || pressed('j'); }
bool DeviceUi::navRight() const { return pressed('/') || pressed('l'); }
bool DeviceUi::enterPressed() const {
  return M5Cardputer.Keyboard.keysState().enter;
}
bool DeviceUi::escapePressed() const { return pressed('`'); }
bool DeviceUi::backspacePressed() const {
  return M5Cardputer.Keyboard.keysState().del;
}
bool DeviceUi::backPressed() const {
  return escapePressed() || backspacePressed();
}

void DeviceUi::handleInput() {
  switch (page_) {
    case Page::Main: handleMain(); break;
    case Page::Codex: handleCodex(); break;
    case Page::Wifi: handleWifi(); break;
    case Page::WifiPassword: handlePassword(); break;
    case Page::Computers: handleComputers(); break;
    case Page::AddComputer: handleAddComputer(); break;
    case Page::PairCode: handlePairCode(); break;
    case Page::Brightness: handleBrightness(); break;
    case Page::ScreenOff: handleScreenOff(); break;
  }
}

void DeviceUi::handleMain() {
  if (navLeft()) {
    if (mainSelection_ == 2) {
      mainSelection_ = 1;
    } else if (mainSelection_ == 4) {
      mainSelection_ = 3;
    } else if (mainSelection_ > 0) {
      homeSettingSelection_ = mainSelection_ - 1;
      mainSelection_ = 0;
    }
  } else if (navRight()) {
    if (mainSelection_ == 0) {
      mainSelection_ = homeSettingSelection_ + 1;
    } else if (mainSelection_ == 1) {
      mainSelection_ = 2;
    } else if (mainSelection_ == 3) {
      mainSelection_ = 4;
    }
  } else if (navUp()) {
    if (mainSelection_ == 3) mainSelection_ = 1;
    if (mainSelection_ == 4) mainSelection_ = 2;
  } else if (navDown()) {
    if (mainSelection_ == 1) mainSelection_ = 3;
    if (mainSelection_ == 2) mainSelection_ = 4;
  } else if (enterPressed()) {
    switch (mainSelection_) {
      case 0:
        showCodex();
        break;
      case 1:
        listSelection_ = 0;
        wifi_.startScan();
        setPage(Page::Wifi);
        break;
      case 2:
        listSelection_ = 0;
        pairing_.requestDiscovery();
        setPage(Page::Computers);
        break;
      case 3:
        setPage(Page::Brightness);
        break;
      case 4:
        setPage(Page::ScreenOff);
        break;
    }
  }
  if (mainSelection_ > 0) homeSettingSelection_ = mainSelection_ - 1;
}

void DeviceUi::handleCodex() {
  const size_t count = pairing_.agentCount();
  if (count > 0 && agentSelection_ >= count) {
    agentSelection_ = count - 1;
    selectedAgentId_ = pairing_.agent(agentSelection_).id;
  }
  if (backPressed()) {
    setPage(Page::Main);
  } else if (count > 0 && navLeft()) {
    agentSelection_ = (agentSelection_ + count - 1) % count;
    selectedAgentId_ = pairing_.agent(agentSelection_).id;
  } else if (count > 0 && navRight()) {
    agentSelection_ = (agentSelection_ + 1) % count;
    selectedAgentId_ = pairing_.agent(agentSelection_).id;
  } else if (count > 0 && enterPressed()) {
    pairing_.sendAgentAck(pairing_.agent(agentSelection_).id);
  }
}

void DeviceUi::handleWifi() {
  const size_t count = wifi_.scanCount();
  if (count > 0 && listSelection_ >= count) listSelection_ = count - 1;
  const auto& state = M5Cardputer.Keyboard.keysState();
  if (state.tab || pressed('r')) {
    wifi_.startScan();
  } else if (backspacePressed() && count > 0 &&
             wifi_.scanResult(listSelection_).saved) {
    wifi_.forget(wifi_.scanResult(listSelection_).ssid);
  } else if (escapePressed()) {
    setPage(Page::Main);
  } else if (count > 0 && navUp()) {
    listSelection_ = (listSelection_ + count - 1) % count;
  } else if (count > 0 && navDown()) {
    listSelection_ = (listSelection_ + 1) % count;
  } else if (count > 0 && enterPressed()) {
    const WifiScanResult& selected = wifi_.scanResult(listSelection_);
    if (selected.saved) {
      for (size_t i = 0; i < wifi_.savedCount(); ++i) {
        if (wifi_.saved(i).ssid == selected.ssid) {
          wifi_.connectSaved(i);
          setPage(Page::Main);
          break;
        }
      }
    } else if (selected.encrypted) {
      pendingSsid_ = selected.ssid;
      textEntry_.clear();
      setPage(Page::WifiPassword);
    } else {
      wifi_.addAndConnect(selected.ssid, "");
      setPage(Page::Main);
    }
  }
}

void DeviceUi::handlePassword() {
  const auto& state = M5Cardputer.Keyboard.keysState();
  if (escapePressed()) {
    setPage(Page::Wifi);
  } else if (state.enter) {
    wifi_.addAndConnect(pendingSsid_, textEntry_);
    textEntry_.clear();
    setPage(Page::Main);
  } else if (state.del) {
    if (!textEntry_.isEmpty()) textEntry_.remove(textEntry_.length() - 1);
  } else {
    appendTypedText(textEntry_, 63, false);
  }
}

void DeviceUi::handleComputers() {
  const size_t rows = pairing_.pairedCount() + 2;  // Add new + Back.
  if (backspacePressed() && listSelection_ < pairing_.pairedCount()) {
    pairing_.deletePairing(listSelection_);
    if (listSelection_ >= pairing_.pairedCount() && listSelection_ > 0) --listSelection_;
  } else if (escapePressed()) {
    setPage(Page::Main);
  } else if (navUp()) {
    listSelection_ = (listSelection_ + rows - 1) % rows;
  } else if (navDown()) {
    listSelection_ = (listSelection_ + 1) % rows;
  } else if (enterPressed()) {
    if (listSelection_ < pairing_.pairedCount()) {
      if (pairing_.pairedCurrent(listSelection_)) {
        pairing_.disconnect(true);
      } else {
        pairing_.connectToPaired(listSelection_);
      }
    } else if (listSelection_ == pairing_.pairedCount()) {
      listSelection_ = 0;
      pairing_.requestDiscovery();
      setPage(Page::AddComputer);
    } else {
      setPage(Page::Main);
    }
  }
}

void DeviceUi::handleAddComputer() {
  const size_t count = pairing_.discoveredCount();
  const auto& state = M5Cardputer.Keyboard.keysState();
  if (state.tab || pressed('r')) {
    pairing_.requestDiscovery();
  } else if (backPressed()) {
    setPage(Page::Computers);
  } else if (count > 0 && navUp()) {
    listSelection_ = (listSelection_ + count - 1) % count;
  } else if (count > 0 && navDown()) {
    listSelection_ = (listSelection_ + 1) % count;
  } else if (count > 0 && enterPressed()) {
    pairing_.connectToDiscovered(listSelection_);
  }
}

void DeviceUi::handlePairCode() {
  const auto& state = M5Cardputer.Keyboard.keysState();
  if (escapePressed()) {
    pairing_.disconnect(true);
    setPage(Page::Computers);
  } else if (state.enter && textEntry_.length() == 6) {
    pairing_.submitPairCode(textEntry_);
  } else if (state.del) {
    if (!textEntry_.isEmpty()) textEntry_.remove(textEntry_.length() - 1);
  } else {
    appendTypedText(textEntry_, 6, true);
  }
}

void DeviceUi::handleBrightness() {
  if (backPressed()) {
    setPage(Page::Main);
    return;
  }
  int direction = 0;
  if (navLeft() || navDown()) direction = -1;
  if (navRight() || navUp() || enterPressed()) direction = 1;
  if (!direction) return;
  const size_t count = sizeof(kBrightnessLevels);
  const size_t current = brightnessLevelIndex(settings_.brightness);
  const size_t next = (current + count + direction) % count;
  settings_.brightness = kBrightnessLevels[next];
  M5Cardputer.Display.setBrightness(settings_.brightness);
  screenDimmed_ = false;
  resetBatteryTrend();
  store_.saveSettings(settings_);
}

void DeviceUi::handleScreenOff() {
  if (backPressed()) {
    setPage(Page::Main);
    return;
  }
  int direction = 0;
  if (navLeft() || navDown()) direction = -1;
  if (navRight() || navUp() || enterPressed()) direction = 1;
  if (!direction) return;
  const size_t count = sizeof(kScreenTimeouts) / sizeof(kScreenTimeouts[0]);
  const size_t current = screenTimeoutIndex(settings_.screenTimeoutSec);
  const size_t next = (current + count + direction) % count;
  settings_.screenTimeoutSec = kScreenTimeouts[next];
  store_.saveSettings(settings_);
  noteActivity();
}

void DeviceUi::appendTypedText(String& destination, size_t maxLength,
                               bool digitsOnly) {
  const auto& state = M5Cardputer.Keyboard.keysState();
  for (char c : state.word) {
    if (destination.length() >= maxLength) break;
    if (digitsOnly && !isDigit(c)) continue;
    if (c >= 32 && c <= 126) destination += c;
  }
}

void DeviceUi::setPage(Page page) {
  page_ = page;
  listSelection_ = 0;
  suppressUntilRelease_ = M5Cardputer.Keyboard.isPressed();
  renderRequested_ = true;
}

void DeviceUi::noteActivity() {
  lastActivityMs_ = millis();
  if (screenDimmed_ && !screenOff_) {
    M5Cardputer.Display.setBrightness(settings_.brightness);
    screenDimmed_ = false;
    resetBatteryTrend();
    renderRequested_ = true;
  }
}

void DeviceUi::wakeScreen() {
  M5Cardputer.Display.wakeup();
  M5Cardputer.Display.setBrightness(settings_.brightness);
  screenOff_ = false;
  screenDimmed_ = false;
  lastBatterySampleMs_ = 0;
  resetBatteryTrend();
  renderRequested_ = true;
}

void DeviceUi::updateScreenPower() {
  if (screenOff_) return;
  const uint32_t inactiveMs = millis() - lastActivityMs_;
  if (settings_.screenTimeoutSec != 0 &&
      inactiveMs >= settings_.screenTimeoutSec * 1000UL) {
    // sleep() turns off both the backlight and the LCD controller instead of
    // leaving the panel scanning invisibly at brightness zero.
    M5Cardputer.Display.sleep();
    screenOff_ = true;
    screenDimmed_ = false;
    resetBatteryTrend();
    return;
  }
  if (!screenDimmed_ && inactiveMs >= kIdleDimAfterMs) {
    const int dimmed = max<int>(kIdleDimMinBrightness,
                                min<int>(kIdleDimMaxBrightness,
                                         settings_.brightness / 3));
    M5Cardputer.Display.setBrightness(static_cast<uint8_t>(dimmed));
    screenDimmed_ = true;
    resetBatteryTrend();
    renderRequested_ = true;
  }
}

void DeviceUi::resetBatteryTrend() {
  batteryTrendBaselineMv_ = batteryVoltageMv_;
  batteryTrendStartedMs_ = millis();
}

void DeviceUi::updateBatteryState(bool force) {
  const uint32_t now = millis();
  const uint32_t sampleInterval = screenOff_ ? kScreenOffBatterySampleMs
                                             : kBatterySampleMs;
  if (!force && lastBatterySampleMs_ != 0 &&
      now - lastBatterySampleMs_ < sampleInterval) {
    return;
  }
  lastBatterySampleMs_ = now;

  const int16_t measuredMv = M5Cardputer.Power.getBatteryVoltage();
  if (measuredMv > 0) {
    batteryVoltageMv_ = batteryVoltageMv_ == 0
                            ? measuredMv
                            : static_cast<int16_t>(
                                  (batteryVoltageMv_ * 3 + measuredMv + 2) / 4);
  }
  const int oldLevel = batteryLevel_;
  if (batteryVoltageMv_ > 0) {
    batteryLevel_ = static_cast<int8_t>(
        batteryPercentFromVoltage(batteryVoltageMv_));
  } else {
    const int reportedLevel = M5Cardputer.Power.getBatteryLevel();
    batteryLevel_ = reportedLevel < 0
                        ? -1
                        : static_cast<int8_t>(min(100, reportedLevel));
  }

  const bool wasUsbPowered = usbPowerPresent_;
  usbPowerPresent_ = static_cast<bool>(USB);
  const auto reportedCharge = M5Cardputer.Power.isCharging();
  const bool directlyCharging =
      reportedCharge == m5::Power_Class::is_charging;
  const bool directlyDischarging =
      reportedCharge == m5::Power_Class::is_discharging;

  if (wasUsbPowered && !usbPowerPresent_) inferredChargingUntilMs_ = 0;
  if (directlyDischarging) inferredChargingUntilMs_ = 0;

  // Cardputer ADV leaves TP4057 CHRG/STDBY disconnected from the MCU. USB
  // enumeration therefore gives immediate evidence for a computer connection;
  // a power-only charger is inferred only from a sustained filtered rise.
  if (!usbPowerPresent_ && !directlyCharging && !directlyDischarging &&
      batteryVoltageMv_ > 0) {
    if (batteryTrendBaselineMv_ == 0) {
      batteryTrendBaselineMv_ = batteryVoltageMv_;
      batteryTrendStartedMs_ = now;
    }
    const uint32_t trendAge = now - batteryTrendStartedMs_;
    const int deltaMv = batteryVoltageMv_ - batteryTrendBaselineMv_;
    if (trendAge >= kBatteryTrendMinMs && deltaMv >= kChargingRiseMv) {
      inferredChargingUntilMs_ = now + kInferredChargingHoldMs;
      batteryTrendBaselineMv_ = batteryVoltageMv_;
      batteryTrendStartedMs_ = now;
    } else if (trendAge >= kBatteryTrendWindowMs) {
      if (deltaMv <= -kDischargingFallMv) inferredChargingUntilMs_ = 0;
      batteryTrendBaselineMv_ = batteryVoltageMv_;
      batteryTrendStartedMs_ = now;
    }
  } else {
    batteryTrendBaselineMv_ = batteryVoltageMv_;
    batteryTrendStartedMs_ = now;
  }

  const bool oldCharging = batteryCharging_;
  batteryCharging_ = directlyCharging || usbPowerPresent_ ||
                     deadlinePending(inferredChargingUntilMs_, now);
  if (batteryLevel_ != oldLevel || batteryCharging_ != oldCharging ||
      usbPowerPresent_ != wasUsbPowered) {
    renderRequested_ = true;
  }
}

uint32_t DeviceUi::renderIntervalMs() const {
  if (millis() - lastActivityMs_ < kInteractiveWindowMs) {
    return kInteractiveRenderMs;
  }
  const PetVisualState visual = codexVisualState();
  const bool animated = visual == PetVisualState::Thinking ||
                        visual == PetVisualState::Running ||
                        visual == PetVisualState::NeedsInput;
  if (!animated) return kStaticRenderMs;
  return screenDimmed_ ? kDimmedAnimatedRenderMs : kAnimatedRenderMs;
}

// -------------------------------------------------------------- drawing --

void DeviceUi::render() {
  if (!canvas_.getBuffer()) return;  // allocation failed — never draw blind
  if (page_ == Page::Main) {
    drawGameBackground();
  } else {
    canvas_.fillSprite(kBackground);
  }
  if (page_ != Page::Codex) drawStatusBar();
  switch (page_) {
    case Page::Main: drawMain(); break;
    case Page::Codex: drawCodex(); break;
    case Page::Wifi: drawWifi(); break;
    case Page::WifiPassword: drawPassword(); break;
    case Page::Computers: drawComputers(); break;
    case Page::AddComputer: drawAddComputer(); break;
    case Page::PairCode: drawPairCode(); break;
    case Page::Brightness: drawBrightness(); break;
    case Page::ScreenOff: drawScreenOff(); break;
  }
  // Explicit destination: the sprite's stored parent pointer is unreliable
  // when the canvas member is constructed before M5Cardputer (static-init
  // order across translation units).
  canvas_.pushSprite(&M5Cardputer.Display, 0, 0);
}

void DeviceUi::drawWifiBars(int x, int y, int rssi, bool connected) {
  drawWifiStrengthIcon(x, y, connected ? rssi : -127, kGood, kPanel);
}

void DeviceUi::drawWifiStrengthIcon(int x, int y, int rssi,
                                    uint16_t active, uint16_t inactive) {
  const int bars = rssi <= -127 ? 0 : rssi > -55 ? 4 : rssi > -65 ? 3
                                  : rssi > -75 ? 2 : 1;
  for (int i = 0; i < 4; ++i) {
    const int h = 3 + i * 3;
    canvas_.fillRect(x + i * 4, y + 12 - h, 3, h,
                     i < bars ? active : inactive);
  }
}

void DeviceUi::drawBattery(int x, int y, bool compact) {
  const int bodyWidth = compact ? 13 : 17;
  const int bodyHeight = compact ? 8 : 10;
  const int terminalHeight = compact ? 4 : 4;
  const uint16_t outline = batteryCharging_ ? kAccentWarm : kTextDim;
  uint16_t fill = batteryLevel_ > 30 ? kGood : kBad;
  if (batteryCharging_) fill = kAccentWarm;

  canvas_.drawRect(x, y, bodyWidth, bodyHeight, outline);
  canvas_.fillRect(x + bodyWidth, y + (bodyHeight - terminalHeight) / 2,
                   2, terminalHeight, outline);
  if (batteryLevel_ > 0) {
    const int innerWidth = bodyWidth - 4;
    canvas_.fillRect(x + 2, y + 2,
                     max(1, innerWidth * batteryLevel_ / 100),
                     bodyHeight - 4, fill);
  }
  if (batteryCharging_) {
    // A small black bolt remains legible over the orange charge fill even at
    // the compact 13x8 detail-page size.
    const int centerX = x + bodyWidth / 2;
    const int middleY = y + bodyHeight / 2;
    canvas_.drawLine(centerX + 1, y + 1, centerX - 2, middleY, TFT_BLACK);
    canvas_.drawLine(centerX - 2, middleY, centerX + 1, middleY, TFT_BLACK);
    canvas_.drawLine(centerX + 1, middleY, centerX - 1,
                     y + bodyHeight - 2, TFT_BLACK);
  }

  const String label = batteryLevel_ < 0
                           ? String("--")
                           : String(static_cast<int>(batteryLevel_)) + "%";
  const uint16_t labelColor = batteryCharging_
                                  ? kAccentWarm
                                  : (batteryLevel_ >= 0 && batteryLevel_ <= 15
                                         ? kBad
                                         : TFT_WHITE);
  canvas_.setTextFont(1);
  canvas_.setTextSize(1);
  canvas_.setTextColor(labelColor);
  canvas_.setTextDatum(middle_left);
  canvas_.drawString(label, x + bodyWidth + 5, y + bodyHeight / 2);
  canvas_.setTextDatum(top_left);
}

void DeviceUi::drawStatusBar() {
  canvas_.fillRect(0, 0, kWidth, kStatusHeight, TFT_BLACK);
  drawKeyboardModeIcon(4, 4);
  drawWifiBars(28, 4, wifi_.rssi(), wifi_.connected());
  drawScrollingTitle(statusBarTitle());
  drawBattery(184, 5);
}

String DeviceUi::statusBarTitle() const {
  switch (page_) {
    case Page::Main: return "CODEX DECK";
    case Page::Codex: {
      const AgentSession* agent = selectedAgent();
      if (!agent) return "Codex";
      if (!agent->title.isEmpty()) return agent->title;
      if (!agent->project.isEmpty()) return agent->project;
      return "Codex";
    }
    case Page::Wifi: return "WiFi";
    case Page::WifiPassword: return "WiFi Password";
    case Page::Computers: return "Computers";
    case Page::AddComputer: return "Add Computer";
    case Page::PairCode: return "Pair Computer";
    case Page::Brightness: return "Brightness";
    case Page::ScreenOff: return "Screen off";
  }
  return "CODEX DECK";
}

void DeviceUi::drawScrollingTitle(const String& title) {
  constexpr int x = 48;
  constexpr int width = 128;
  if (title != marqueeTitle_) {
    marqueeTitle_ = title;
    marqueeStartedMs_ = millis();
  }
  canvas_.setFont(uiFontFace_);
  canvas_.setTextColor(TFT_WHITE, TFT_BLACK);
  const int textWidth = canvas_.textWidth(title);
  canvas_.setClipRect(x, 0, width, kStatusHeight);
  canvas_.setTextDatum(middle_left);
  if (textWidth <= width) {
    canvas_.drawString(title, x + (width - textWidth) / 2, 10);
  } else {
    const uint32_t elapsed = millis() - marqueeStartedMs_;
    const int travel = textWidth + 28;
    const int offset = elapsed < 1200 ? 0 : ((elapsed - 1200) / 40) % travel;
    canvas_.drawString(title, x - offset, 10);
    canvas_.drawString(title, x - offset + travel, 10);
  }
  canvas_.clearClipRect();
  canvas_.setTextDatum(top_left);
  canvas_.setTextFont(1);
}

void DeviceUi::drawCodexTitle(const String& title) {
  if (title != marqueeTitle_) {
    marqueeTitle_ = title;
    marqueeStartedMs_ = millis();
  }
  canvas_.setFont(uiFontFace_);
  canvas_.setTextSize(1.0f);
  canvas_.setTextColor(TFT_WHITE, kBackground);
  const int textWidth = canvas_.textWidth(title);
  canvas_.setClipRect(kCodexContentX, kCodexTitleY, kCodexContentWidth,
                      kCodexTitleHeight);
  canvas_.setTextDatum(middle_left);
  if (textWidth <= kCodexContentWidth) {
    canvas_.drawString(title, kCodexContentX,
                       kCodexTitleY + kCodexTitleHeight / 2);
  } else {
    const uint32_t elapsed = millis() - marqueeStartedMs_;
    const int travel = textWidth + 18;
    const int offset = elapsed < 1000 ? 0 : ((elapsed - 1000) / 45) % travel;
    canvas_.drawString(title, kCodexContentX - offset,
                       kCodexTitleY + kCodexTitleHeight / 2);
    canvas_.drawString(title, kCodexContentX - offset + travel,
                       kCodexTitleY + kCodexTitleHeight / 2);
  }
  canvas_.clearClipRect();
  canvas_.setTextDatum(top_left);
  canvas_.setTextFont(1);
}

void DeviceUi::drawCodexSessionBadge(size_t index, size_t count) {
  if (count == 0) return;
  canvas_.setTextFont(1);
  canvas_.setTextSize(1);
  canvas_.setTextDatum(middle_center);
  const String label = String(index + 1) + "/" + String(count);
  const int centerX = kCodexSessionBadgeX + kCodexSessionBadgeWidth / 2;
  const int centerY = kCodexSessionBadgeY + kCodexSessionBadgeHeight / 2;
  canvas_.setTextColor(kBackground);
  canvas_.drawString(label, centerX + 1, centerY + 1);
  canvas_.setTextColor(TFT_WHITE);
  canvas_.drawString(label, centerX, centerY);
  canvas_.setTextDatum(top_left);
}

String DeviceUi::fitWithEllipsis(String text, int width, bool force) {
  canvas_.setFont(uiFontFace_);
  if (!force && canvas_.textWidth(text) <= width) return text;
  const String suffix = "...";
  while (!text.isEmpty() && canvas_.textWidth(text + suffix) > width) {
    removeLastUtf8Character(text);
  }
  return text + suffix;
}

void DeviceUi::prepareCodexActivity(const String& activity) {
  if (activity == wrappedActivity_) return;
  wrappedActivity_ = activity;
  activityLineCount_ = 0;
  for (String& line : activityLines_) line.clear();
  canvas_.setFont(uiFontFace_);
  canvas_.setTextSize(kCodexActivityTextScale);

  bool overflow = false;
  String current;
  auto pushLine = [&](const String& line) {
    if (line.isEmpty()) return true;
    if (activityLineCount_ >= kCodexActivityLines) {
      overflow = true;
      return false;
    }
    activityLines_[activityLineCount_++] = line;
    return true;
  };

  size_t cursor = 0;
  while (cursor < activity.length() && !overflow) {
    while (cursor < activity.length() &&
           isspace(static_cast<unsigned char>(activity[cursor]))) {
      ++cursor;
    }
    const size_t start = cursor;
    while (cursor < activity.length() &&
           !isspace(static_cast<unsigned char>(activity[cursor]))) {
      ++cursor;
    }
    if (start == cursor) continue;
    const String token = activity.substring(start, cursor);
    const String candidate = current.isEmpty() ? token : current + " " + token;
    if (canvas_.textWidth(candidate) <= kCodexContentWidth) {
      current = candidate;
      continue;
    }

    if (!current.isEmpty()) {
      if (!pushLine(current)) break;
      current.clear();
    }
    if (canvas_.textWidth(token) <= kCodexContentWidth) {
      current = token;
      continue;
    }
    if (asciiOnly(token)) {
      if (!pushLine(fitWithEllipsis(token, kCodexContentWidth, false))) break;
      continue;
    }

    // Chinese may wrap at character boundaries, but an embedded ASCII run is
    // kept intact so names such as CardBridge never split letter by letter.
    String chunk;
    for (size_t index = 0; index < token.length() && !overflow;) {
      size_t end = index;
      if (static_cast<uint8_t>(token[index]) < 0x80) {
        while (end < token.length() &&
               static_cast<uint8_t>(token[end]) < 0x80) {
          ++end;
        }
      } else {
        end += utf8CharacterLength(token, index);
      }
      const String segment = token.substring(index, end);
      if (canvas_.textWidth(segment) > kCodexContentWidth) {
        if (!chunk.isEmpty() && !pushLine(chunk)) break;
        chunk.clear();
        if (!pushLine(fitWithEllipsis(segment, kCodexContentWidth, false))) break;
        index = end;
        continue;
      }
      const String expanded = chunk + segment;
      if (!chunk.isEmpty() &&
          canvas_.textWidth(expanded) > kCodexContentWidth) {
        if (!pushLine(chunk)) break;
        chunk = segment;
      } else {
        chunk = expanded;
      }
      index = end;
    }
    current = chunk;
  }

  if (!overflow && !current.isEmpty()) pushLine(current);
  if (cursor < activity.length()) overflow = true;
  if (overflow && activityLineCount_ > 0) {
    const uint8_t last = activityLineCount_ - 1;
    activityLines_[last] =
        fitWithEllipsis(activityLines_[last], kCodexContentWidth, true);
  }
  canvas_.setTextSize(1.0f);
  canvas_.setTextFont(1);
}

void DeviceUi::drawCodexActivity(const String& activity) {
  prepareCodexActivity(activity);
  canvas_.setFont(uiFontFace_);
  canvas_.setTextSize(kCodexActivityTextScale);
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setTextDatum(top_left);
  canvas_.setClipRect(kCodexContentX, kCodexActivityY, kCodexContentWidth,
                      kCodexActivityHeight);
  for (uint8_t line = 0; line < activityLineCount_; ++line) {
    canvas_.drawString(activityLines_[line], kCodexContentX,
                       kCodexActivityY + kCodexActivityTextInsetY +
                           line * kCodexActivityLinePitch);
  }
  canvas_.clearClipRect();
  canvas_.setTextSize(1.0f);
  canvas_.setTextFont(1);
}

void DeviceUi::drawKeyboardModeIcon(int x, int y) {
  const bool enabled = mode_ == UiMode::Remote;
  const uint16_t color = enabled ? kAccent : kTextDim;
  if (enabled) {
    canvas_.fillRoundRect(x, y, 18, 12, 2, color);
  } else {
    canvas_.drawRoundRect(x, y, 18, 12, 2, color);
  }
  const uint16_t keyColor = enabled ? TFT_BLACK : color;
  for (int column = 0; column < 4; ++column) {
    canvas_.fillRect(x + 3 + column * 3, y + 3, 2, 2, keyColor);
  }
  canvas_.fillRect(x + 3, y + 7, 12, 2, keyColor);
  if (!enabled) canvas_.drawLine(x + 2, y + 11, x + 16, y + 1, kBad);
}

void DeviceUi::drawHint(const String& text) {
  canvas_.setTextSize(1);
  canvas_.setTextColor(kTextDim, kBackground);
  canvas_.setTextDatum(bottom_center);
  canvas_.drawString(text, kWidth / 2, kHeight - 3);
  canvas_.setTextDatum(top_left);
}

void DeviceUi::drawGameBackground() {
  canvas_.fillSprite(kBackground);
  for (int x = 15; x < kWidth; x += 46) {
    canvas_.drawFastVLine(x, 19, kHeight - 19, kLine);
  }
  canvas_.drawFastHLine(0, 76, kWidth, kLine);
  const int pulse = (millis() / 500) % 3;
  canvas_.drawFastHLine(2 + pulse, 132, 52, kLine);
  canvas_.drawFastHLine(185 - pulse, 132, 50, kLine);
}

void DeviceUi::drawAngularPanel(int x, int y, int width, int height,
                                bool selected) {
  const uint16_t background = selected ? kPanelSelected : kPanel;
  canvas_.fillRect(x + 2, y, width - 4, height, background);
  canvas_.fillRect(x, y + 2, width, height - 4, background);
  canvas_.drawRect(x + 2, y + 2, width - 4, height - 4, kLine);
  const uint16_t edge = selected ? kAccent : kLine;
  canvas_.drawFastHLine(x, y + 2, 7, edge);
  canvas_.drawFastVLine(x, y + 2, 7, edge);
  canvas_.drawFastHLine(x + width - 7, y + 2, 7, edge);
  canvas_.drawFastVLine(x + width - 1, y + 2, 7, edge);
  canvas_.drawFastHLine(x, y + height - 3, 7, edge);
  canvas_.drawFastVLine(x, y + height - 8, 7, edge);
  canvas_.drawFastHLine(x + width - 7, y + height - 3, 7, edge);
  canvas_.drawFastVLine(x + width - 1, y + height - 8, 7, edge);
}

void DeviceUi::drawWorkshopStage(int x, int y, int width, int height,
                                 PetVisualState state) {
  canvas_.fillRect(x, y, width, height, kPanelDeep);
  canvas_.drawRect(x, y, width, height, kLine);
  canvas_.fillRect(x + 3, y + 3, width - 6, height * 42 / 100, kBackground);
  const int horizon = y + height * 46 / 100;
  canvas_.fillRect(x + 3, horizon, width - 6, y + height - horizon - 3,
                   kPanel);
  canvas_.drawFastHLine(x + 3, horizon + 8, width - 6, kLine);
  canvas_.drawFastHLine(x + 3, horizon + 23, width - 6, kLine);
  canvas_.drawLine(x + width / 2, horizon + 2, x + width / 2 - 14,
                   y + height - 3, kLine);
  canvas_.drawLine(x + width / 2, horizon + 2, x + width / 2 + 14,
                   y + height - 3, kLine);
  canvas_.fillRect(x + 5, horizon + 2, 15, 3, kLine);
  canvas_.fillRect(x + width - 20, horizon + 2, 15, 3, kLine);
  if (state == PetVisualState::Thinking || state == PetVisualState::Running) {
    const int scanX = x + 5 + (millis() / 90) % max(1, width - 10);
    canvas_.drawFastVLine(scanX, y + 4, height * 36 / 100, kAccent);
  }
}

void DeviceUi::drawWorkshopMonitor(PetVisualState state, uint32_t now) {
  constexpr int frameX = 7;
  constexpr int frameY = 26;
  constexpr int frameWidth = 42;
  constexpr int frameHeight = 31;
  constexpr int screenX = 11;
  constexpr int screenY = 31;
  constexpr int screenWidth = 34;
  constexpr int screenHeight = 18;

  uint16_t signalColor = kAccent;
  if (state == PetVisualState::NeedsInput) {
    signalColor = kAccentWarm;
  } else if (state == PetVisualState::Ready) {
    signalColor = kGood;
  } else if (state == PetVisualState::Blocked ||
             state == PetVisualState::Offline) {
    signalColor = kBad;
  } else if (state == PetVisualState::Idle) {
    signalColor = kTextDim;
  }

  // A wall-mounted terminal gives all motion a visible source instead of
  // scattering decorative scan lines and particles across the room.
  canvas_.fillRect(frameX + 3, frameY - 3, frameWidth - 6, 3, kLine);
  canvas_.fillRect(frameX + 5, frameY + frameHeight, frameWidth - 10, 2,
                   kPanelDeep);
  canvas_.fillRoundRect(frameX, frameY, frameWidth, frameHeight, 4,
                        kPanelDeep);
  canvas_.drawRoundRect(frameX, frameY, frameWidth, frameHeight, 4, kLine);
  canvas_.fillRect(frameX + frameWidth - 4, frameY + 7, 2, 12,
                   blendRgb565(kPanelDeep, signalColor, 48));

  const bool active = state == PetVisualState::Thinking ||
                      state == PetVisualState::Running;
  const int glowPhase = (now / 45) % 48;
  const int glowTriangle = glowPhase <= 24 ? glowPhase : 48 - glowPhase;
  const uint8_t glow = active ? 42 + glowTriangle : 32;
  const uint16_t screenBackground =
      blendRgb565(kBackground, signalColor, glow / 3);
  canvas_.fillRoundRect(screenX, screenY, screenWidth, screenHeight, 2,
                        screenBackground);
  canvas_.drawRoundRect(screenX, screenY, screenWidth, screenHeight, 2,
                        blendRgb565(kLine, signalColor, glow));

  const int contentLeft = screenX + 3;
  const int contentTop = screenY + 3;
  const int contentWidth = screenWidth - 6;
  const int contentHeight = screenHeight - 6;
  if (active) {
    // A scrolling telemetry waveform is contained inside the terminal and
    // speeds up while Codex is running.
    const int speed = state == PetVisualState::Running ? 70 : 120;
    const int phase = (now / speed) % 12;
    const int centerY = contentTop + contentHeight / 2;
    int previousY = centerY;
    for (int offset = 0; offset < contentWidth; ++offset) {
      const int sample = (offset + phase) % 12;
      int wave = 0;
      if (sample == 2) wave = -1;
      if (sample == 3) wave = -4;
      if (sample == 4) wave = 3;
      if (sample == 5) wave = 1;
      const int y = centerY + wave;
      if (offset > 0) {
        canvas_.drawLine(contentLeft + offset - 1, previousY,
                         contentLeft + offset, y, signalColor);
      }
      previousY = y;
    }
    const int meterWidth = 5 + (now / speed) % (contentWidth - 4);
    canvas_.drawFastHLine(contentLeft, screenY + screenHeight - 3,
                          meterWidth,
                          blendRgb565(screenBackground, signalColor, 112));
  } else if (state == PetVisualState::Ready) {
    // Stable check mark: completed work should feel calm, not blink.
    canvas_.drawLine(contentLeft + 6, contentTop + 5,
                     contentLeft + 10, contentTop + 9, signalColor);
    canvas_.drawLine(contentLeft + 10, contentTop + 9,
                     contentLeft + 19, contentTop + 1, signalColor);
    canvas_.drawLine(contentLeft + 6, contentTop + 6,
                     contentLeft + 10, contentTop + 10, signalColor);
  } else if (state == PetVisualState::NeedsInput) {
    // A slow terminal cursor provides a deliberate prompt without random
    // flashing pixels elsewhere in the scene.
    canvas_.fillRect(contentLeft + 12, contentTop + 1, 3, 6, signalColor);
    if ((now / 650) % 2 == 0) {
      canvas_.fillRect(contentLeft + 12, contentTop + 9, 3, 2, signalColor);
    }
  } else if (state == PetVisualState::Blocked ||
             state == PetVisualState::Offline) {
    canvas_.drawLine(contentLeft + 8, contentTop + 2,
                     contentLeft + 19, contentTop + 10, signalColor);
    canvas_.drawLine(contentLeft + 19, contentTop + 2,
                     contentLeft + 8, contentTop + 10, signalColor);
  } else {
    // Idle terminal: a recognizable power glyph, intentionally static.
    canvas_.drawCircle(contentLeft + 14, contentTop + 6, 5, signalColor);
    canvas_.drawFastVLine(contentLeft + 14, contentTop, 6, signalColor);
    canvas_.drawPixel(contentLeft + 14, contentTop + 6, screenBackground);
  }

  canvas_.fillRect(frameX + frameWidth - 9, frameY + frameHeight - 4, 3, 2,
                   signalColor);
}

void DeviceUi::drawWorkshopDataConduit(PetVisualState state, uint32_t now) {
  // Twin channels are centered roughly ten pixels left of the original
  // single conduit. The pet may occlude the left channel, which reinforces
  // the intended foreground/background depth.
  constexpr int frameX[] = {87, 99};
  constexpr int frameY = 22;
  constexpr int frameWidth = 10;
  constexpr int frameHeight = 65;
  constexpr int tubeY = 29;
  constexpr int tubeWidth = 4;
  constexpr int tubeHeight = 48;
  constexpr int columnCount = sizeof(frameX) / sizeof(frameX[0]);

  uint16_t signalColor = kAccent;
  if (state == PetVisualState::NeedsInput) signalColor = kAccentWarm;
  if (state == PetVisualState::Ready) signalColor = kGood;
  if (state == PetVisualState::Blocked || state == PetVisualState::Offline) {
    signalColor = kBad;
  }
  if (state == PetVisualState::Idle) signalColor = kTextDim;

  const bool active = state == PetVisualState::Thinking ||
                      state == PetVisualState::Running;
  const int breathPhase = (now / 55) % 48;
  const int breath = breathPhase <= 24 ? breathPhase : 48 - breathPhase;
  const uint16_t tubeBackground =
      blendRgb565(kBackground, signalColor, 18);

  for (int column = 0; column < columnCount; ++column) {
    const int x = frameX[column];
    const int tubeX = x + 3;

    canvas_.fillRect(x + 2, frameY - 3, frameWidth - 4, 3, kLine);
    canvas_.fillRoundRect(x, frameY, frameWidth, frameHeight, 2,
                          kPanelDeep);
    canvas_.drawRoundRect(x, frameY, frameWidth, frameHeight, 2, kLine);
    canvas_.fillRect(x + 2, frameY + 4, frameWidth - 4, 2, kPanel);
    canvas_.fillRect(x + 2, frameY + frameHeight - 6,
                     frameWidth - 4, 2, kPanel);
    canvas_.fillRect(tubeX, tubeY, tubeWidth, tubeHeight, tubeBackground);
    canvas_.drawRect(tubeX - 1, tubeY - 1, tubeWidth + 2, tubeHeight + 2,
                     blendRgb565(kLine, signalColor, 42));
    canvas_.drawFastHLine(x + 1, tubeY + 15, frameWidth - 2, kLine);
    canvas_.drawFastHLine(x + 1, tubeY + 32, frameWidth - 2, kLine);

    if (active) {
      const int speed = state == PetVisualState::Running ? 68 : 108;
      constexpr int packetHeight = 5;
      constexpr int travel = tubeHeight - packetHeight;
      constexpr int loopLength = travel + 15;
      // The second channel trails the first so the pair feels like one machine
      // with two data lanes rather than duplicated sprites.
      const int phase = ((now / speed) + column * 9) % loopLength;
      for (int packet = 0; packet < 3; ++packet) {
        const int offset = (phase + packet * 19) % loopLength;
        if (offset > travel) continue;
        const int edgeFade = min(offset, travel - offset);
        const uint8_t amount = min(176, 112 + max(0, edgeFade));
        canvas_.fillRect(tubeX + 1, tubeY + offset, tubeWidth - 2,
                         packetHeight,
                         blendRgb565(tubeBackground, signalColor, amount));
        canvas_.drawFastHLine(tubeX + 1, tubeY + offset, tubeWidth - 2,
                              signalColor);
      }
    } else if (state == PetVisualState::Ready) {
      // Fill once from top to bottom after entering Ready, then remain full.
      // A vertical intensity gradient and a slow whole-column breath make
      // success feel stored/complete instead of replaying a travelling cell.
      constexpr uint32_t fillDurationMs = 1500;
      constexpr uint32_t columnDelayMs = 140;
      const uint32_t stateElapsed = now - codexEffectStateStartedMs_;
      const uint32_t delay = column * columnDelayMs;
      const uint32_t columnElapsed =
          stateElapsed > delay ? stateElapsed - delay : 0;
      const int filledRows = columnElapsed >= fillDurationMs
                                 ? tubeHeight
                                 : columnElapsed * tubeHeight / fillDurationMs;
      const bool full = filledRows >= tubeHeight;
      const int readyBreathPhase = full ? (columnElapsed / 55) % 64 : 0;
      const int readyBreath = readyBreathPhase <= 32
                                  ? readyBreathPhase
                                  : 64 - readyBreathPhase;
      const uint32_t maturityValue =
          columnElapsed * 48 / fillDurationMs;
      const int maturity = maturityValue > 48 ? 48 : maturityValue;
      for (int row = 0; row < filledRows; ++row) {
        const int verticalGradient = row * 54 / (tubeHeight - 1);
        const int breathingBoost = full ? readyBreath * 3 / 2 : 0;
        const uint8_t amount = min(220,
            58 + maturity + verticalGradient + breathingBoost);
        canvas_.drawFastHLine(tubeX, tubeY + row, tubeWidth,
                              blendRgb565(tubeBackground, signalColor,
                                          amount));
      }
      if (filledRows > 0 && !full) {
        canvas_.drawFastHLine(tubeX, tubeY + filledRows - 1,
                              tubeWidth, signalColor);
      }
    } else if (state == PetVisualState::NeedsInput) {
      const int promptY = tubeY + tubeHeight / 2 - 5 + column * 4;
      canvas_.fillRect(tubeX + 1, promptY, tubeWidth - 2, 7,
                       blendRgb565(tubeBackground, signalColor,
                                   92 + breath * 3));
    } else if (state == PetVisualState::Blocked ||
               state == PetVisualState::Offline) {
      const int centerY = tubeY + tubeHeight / 2;
      canvas_.drawLine(tubeX, centerY - 4, tubeX + tubeWidth - 1,
                       centerY + 4, signalColor);
      canvas_.drawLine(tubeX + tubeWidth - 1, centerY - 4, tubeX,
                       centerY + 4, signalColor);
    } else {
      canvas_.fillRect(tubeX + 1, tubeY + tubeHeight - 5,
                       tubeWidth - 2, 3,
                       blendRgb565(tubeBackground, signalColor, 92));
    }

    canvas_.fillRect(x + 4, frameY + frameHeight - 4, 3, 2,
                     signalColor);
  }

  // Both channels converge into one physical junction before entering the
  // stage. These cables are drawn behind the pet by the scene ordering.
  const uint8_t cableGlow = active ? 42 + breath * 2 : 30;
  const uint16_t cableColor = blendRgb565(kLine, signalColor, cableGlow);
  constexpr int junctionX = 103;
  constexpr int junctionY = 98;
  for (int column = 0; column < columnCount; ++column) {
    const int portX = frameX[column] + frameWidth / 2;
    canvas_.fillRect(portX - 1, frameY + frameHeight, 3, 5, kPanelDeep);
    canvas_.drawFastVLine(portX, frameY + frameHeight, 7, cableColor);
    canvas_.drawLine(portX, frameY + frameHeight + 6,
                     junctionX, junctionY, cableColor);
  }
  canvas_.fillRoundRect(junctionX - 3, junctionY - 2, 7, 5, 2,
                        kPanelDeep);
  canvas_.drawRoundRect(junctionX - 3, junctionY - 2, 7, 5, 2,
                        cableColor);
  canvas_.drawLine(junctionX, junctionY + 3, 99, 108, cableColor);
}

void DeviceUi::drawCodexScene(PetVisualState state) {
  // kPixels contains native uint16_t RGB565 words. M5GFX defaults uint16_t
  // image input to byte-swapped RGB565 (the common wire/file representation),
  // which turns the intended navy/cyan palette yellow on little-endian ESP32.
  // Opt into native-word input only for this upload and restore the caller's
  // setting so other canvas operations keep their existing behavior.
  const bool previousSwapBytes = canvas_.getSwapBytes();
  canvas_.setSwapBytes(true);
  canvas_.pushImage(0, 0, ui_background_asset::kWidth,
                    ui_background_asset::kHeight,
                    ui_background_asset::kPixels);
  canvas_.setSwapBytes(previousSwapBytes);
  const uint32_t now = millis();

  drawWorkshopMonitor(state, now);
  drawWorkshopDataConduit(state, now);

  // Grounding shadow stays behind the pet. The illuminated front lip is drawn
  // later, after the pet, so the platform reads as a three-dimensional stage.
  canvas_.fillEllipse(56, 112, 27, 4, kPanelDeep);
}

void DeviceUi::drawCodexPlatformEffect(PetVisualState state, uint32_t now) {
  // The generated platform's visual center sits slightly right of the pet's
  // nominal 100 px viewport center. Align the foreground energy with the art.
  constexpr int centerX = 60;
  constexpr int centerY = 110;
  // Coarse points deliberately match the low-resolution pixel-art scene. Only
  // the near half of the ellipse is represented; the rear half remains hidden
  // behind the pet and platform top.
  constexpr int8_t arcX[] = {
      -42, -40, -36, -30, -22, -12, 0, 12, 22, 30, 36, 40, 42,
  };
  constexpr int8_t arcY[] = {
      0, 3, 5, 7, 9, 10, 10, 10, 9, 7, 5, 3, 0,
  };
  constexpr int arcPointCount = sizeof(arcX) / sizeof(arcX[0]);

  uint16_t platformColor = kAccent;
  if (state == PetVisualState::NeedsInput) platformColor = kAccentWarm;
  if (state == PetVisualState::Ready) platformColor = kGood;
  if (state == PetVisualState::Blocked || state == PetVisualState::Offline) {
    platformColor = kBad;
  }

  auto drawFrontArc = [&](int lift, uint16_t color) {
    const uint16_t lowerEdge = blendRgb565(kBackground, color, 148);
    for (int index = 1; index < arcPointCount; ++index) {
      canvas_.drawLine(centerX + arcX[index - 1],
                       centerY + arcY[index - 1] - lift,
                       centerX + arcX[index],
                       centerY + arcY[index] - lift, color);
      canvas_.drawLine(centerX + arcX[index - 1],
                       centerY + arcY[index - 1] - lift + 1,
                       centerX + arcX[index],
                       centerY + arcY[index] - lift + 1, lowerEdge);
    }
  };

  auto drawFrontArcSegment = [&](int segment, int lift, uint16_t color) {
    if (segment < 0 || segment >= arcPointCount - 1) return;
    const uint16_t lowerEdge = blendRgb565(kBackground, color, 148);
    canvas_.drawLine(centerX + arcX[segment],
                     centerY + arcY[segment] - lift,
                     centerX + arcX[segment + 1],
                     centerY + arcY[segment + 1] - lift, color);
    canvas_.drawLine(centerX + arcX[segment],
                     centerY + arcY[segment] - lift + 1,
                     centerX + arcX[segment + 1],
                     centerY + arcY[segment + 1] - lift + 1, lowerEdge);
  };

  const bool platformActive = state == PetVisualState::Thinking ||
                              state == PetVisualState::Running;
  const int breathPhase = (now / 50) % 64;
  const int breathTriangle =
      breathPhase <= 32 ? breathPhase : 64 - breathPhase;
  uint8_t baseGlow = 68;
  if (platformActive) {
    baseGlow = 58 + breathTriangle * 2;
  } else if (state == PetVisualState::Idle) {
    baseGlow = 48;
  } else if (state == PetVisualState::Ready) {
    baseGlow = 76;
  } else if (state == PetVisualState::NeedsInput) {
    baseGlow = 72;
  }

  if (platformActive) {
    // Three evenly spaced energy layers rise from the near rim. Each layer
    // fades as it climbs, and the shared breathing envelope keeps the loop
    // soft instead of producing a flashing reset.
    const int speed = state == PetVisualState::Running ? 72 : 105;
    const int travelPhase = (now / speed) % 15;
    for (int layer = 0; layer < 3; ++layer) {
      const int lift = (travelPhase + layer * 5) % 15;
      const int fade = 15 - lift;
      const uint8_t amount =
          min(144, 20 + fade * 5 + breathTriangle);
      drawFrontArc(lift,
                   blendRgb565(kBackground, platformColor, amount));
    }
  } else if (state == PetVisualState::NeedsInput) {
    // One restrained amber layer breathes in place while waiting for input.
    drawFrontArc(3, blendRgb565(kBackground, platformColor,
                                56 + breathTriangle * 2));
  } else if (state == PetVisualState::Ready) {
    // Completion confirmation: highlights close from both sides, meet in the
    // center, then release two calm green echoes upward. The four-second loop
    // makes the result visible without turning Ready into constant motion.
    const int readyPhase = (now / 80) % 52;
    constexpr int segmentCount = arcPointCount - 1;
    constexpr int halfSegments = segmentCount / 2;
    if (readyPhase < 12) {
      const int closedSegments = min(halfSegments, readyPhase / 2 + 1);
      const uint16_t closeColor =
          blendRgb565(kBackground, platformColor, 172);
      for (int offset = 0; offset < closedSegments; ++offset) {
        drawFrontArcSegment(offset, 0, closeColor);
        drawFrontArcSegment(segmentCount - 1 - offset, 0, closeColor);
      }
    } else if (readyPhase < 28) {
      const int lift = readyPhase - 12;
      const uint8_t primaryAmount = max(36, 172 - lift * 7);
      drawFrontArc(lift,
                   blendRgb565(kBackground, platformColor, primaryAmount));
      if (lift >= 5) {
        const int secondLift = lift - 5;
        const uint8_t secondaryAmount = max(30, 112 - secondLift * 6);
        drawFrontArc(secondLift,
                     blendRgb565(kBackground, platformColor,
                                 secondaryAmount));
      }
      if (lift < 5) {
        canvas_.drawFastVLine(centerX, centerY + 5 - lift, 4,
                              blendRgb565(kBackground, platformColor,
                                          136 - lift * 12));
      }
    }
  }

  // The solid front lip is drawn last. It hides the roots of the rising
  // layers and sells the platform's foreground depth.
  drawFrontArc(0,
               blendRgb565(kBackground, platformColor, baseGlow));
  for (int index = 4; index < arcPointCount - 4; ++index) {
    canvas_.drawPixel(centerX + arcX[index],
                      centerY + arcY[index] + 1,
                      blendRgb565(kPanelDeep, platformColor,
                                  max(24, baseGlow - 18)));
  }
}

void DeviceUi::drawHomeStatusLine(int x, int y, int width,
                                  PetVisualState state) {
  canvas_.fillRect(x, y, width, 3, kBackground);
  if (state == PetVisualState::Thinking || state == PetVisualState::Running) {
    const int segmentWidth = state == PetVisualState::Running ? 24 : 16;
    const int travel = width - segmentWidth;
    const int speed = state == PetVisualState::Running ? 45 : 75;
    const int step = (millis() / speed) % (travel * 2);
    const int offset = step <= travel ? step : travel * 2 - step;
    canvas_.fillRect(x + offset, y, segmentWidth, 3, kAccent);
  } else if (state == PetVisualState::NeedsInput) {
    const int promptWidth = (millis() / 320) % 2 == 0 ? width : width * 3 / 5;
    canvas_.fillRect(x, y, promptWidth, 3, kAccentWarm);
  } else if (state == PetVisualState::Blocked ||
             state == PetVisualState::Offline) {
    canvas_.fillRect(x, y, width, 3, kBad);
  } else if (state == PetVisualState::Ready) {
    canvas_.fillRect(x, y, width, 3, kGood);
  } else {
    canvas_.fillRect(x, y, 24, 3, kTextDim);
  }
}

void DeviceUi::drawMain() {
  const PetVisualState visual = codexVisualState();
  drawAngularPanel(4, 24, 108, 105, mainSelection_ == 0);
  drawWorkshopStage(9, 29, 98, 63, visual);
  pet_.draw(canvas_, visual, 22, 25, millis());
  canvas_.fillRect(9, 95, 98, 30, kPanelDeep);
  canvas_.drawFastHLine(9, 95, 98, kLine);
  canvas_.fillRect(13, 99, 3, 3, codexStatusColor());
  canvas_.setTextFont(1);
  canvas_.setTextSize(1);
  canvas_.setTextColor(TFT_WHITE, kPanelDeep);
  canvas_.setTextDatum(top_left);
  canvas_.drawString("CODEX", 20, 97);
  canvas_.setTextColor(codexStatusColor(), kPanelDeep);
  canvas_.setTextDatum(top_right);
  canvas_.drawString(codexStatusLabel(visual), 103, 97);
  canvas_.setTextDatum(top_left);
  drawHomeStatusLine(13, 116, 89, visual);

  drawAngularPanel(118, 24, 58, 50, mainSelection_ == 1);
  drawAngularPanel(179, 24, 57, 50, mainSelection_ == 2);
  drawAngularPanel(118, 79, 58, 50, mainSelection_ == 3);
  drawAngularPanel(179, 79, 57, 50, mainSelection_ == 4);

  drawWifiStrengthIcon(139, 33, wifi_.rssi(),
                       wifi_.connected() ? kGood : kBad, kLine);
  canvas_.drawRect(199, 34, 16, 12, pairing_.connected() ? kGood : kTextDim);
  canvas_.drawFastHLine(202, 49, 10, pairing_.connected() ? kGood : kTextDim);
  canvas_.drawFastVLine(207, 46, 4, pairing_.connected() ? kGood : kTextDim);

  canvas_.fillRect(141, 89, 12, 12, kAccentWarm);
  canvas_.drawFastVLine(147, 84, 4, kAccentWarm);
  canvas_.drawFastVLine(147, 102, 4, kAccentWarm);
  canvas_.drawFastHLine(136, 95, 4, kAccentWarm);
  canvas_.drawFastHLine(154, 95, 4, kAccentWarm);

  const uint16_t sleepBackground = mainSelection_ == 4 ? kPanelSelected : kPanel;
  constexpr uint16_t violet = 0x793B;
  canvas_.fillCircle(207, 95, 10, violet);
  canvas_.fillCircle(212, 91, 9, sleepBackground);

  const int brightnessPercent = (settings_.brightness * 100 + 127) / 255;
  const String timeoutValue = settings_.screenTimeoutSec == 0
      ? String("ON") : String(settings_.screenTimeoutSec) + "S";
  canvas_.setTextDatum(middle_center);
  canvas_.setTextColor(TFT_WHITE);
  canvas_.drawString("WIFI", 147, 64);
  canvas_.drawString("MAC", 207, 64);
  canvas_.drawString(String(brightnessPercent) + "%", 147, 119);
  canvas_.drawString(timeoutValue, 207, 119);
  canvas_.setTextDatum(top_left);
}

void DeviceUi::drawHomeSettingRow(int y, uint8_t index, const String& text,
                                  const String& value) {
  constexpr int x = 118;
  constexpr int width = 118;
  constexpr int height = 23;
  const bool selected = mainSelection_ == index + 1;
  const uint16_t background = selected ? kPanelSelected : kPanel;
  canvas_.fillRoundRect(x, y, width, height, 5, background);
  if (selected) canvas_.drawRoundRect(x, y, width, height, 5, kAccent);
  canvas_.setTextFont(1);
  canvas_.setTextSize(1);
  canvas_.setTextColor(selected ? TFT_WHITE : kTextDim, background);
  canvas_.setCursor(x + 7, y + 8);
  canvas_.print(text);
  if (!value.isEmpty()) {
    const int valueWidth = canvas_.textWidth(value);
    canvas_.setTextColor(selected ? TFT_WHITE : kAccent, background);
    canvas_.setCursor(x + width - valueWidth - 6, y + 8);
    canvas_.print(value);
  }
}

const AgentSession* DeviceUi::selectedAgent() const {
  if (pairing_.agentCount() == 0 || agentSelection_ >= pairing_.agentCount()) {
    return nullptr;
  }
  return &pairing_.agent(agentSelection_);
}

PetVisualState DeviceUi::codexVisualState() const {
  if (!pairing_.connected()) return PetVisualState::Offline;
  const AgentSession* agent = selectedAgent();
  if (!agent || !pairing_.agentOnline()) return PetVisualState::Idle;
  switch (agent->status) {
    case AgentStatus::Running:
      return agent->phase == AgentPhase::Tool
          ? PetVisualState::Running : PetVisualState::Thinking;
    case AgentStatus::NeedsInput: return PetVisualState::NeedsInput;
    case AgentStatus::Ready: return PetVisualState::Ready;
    case AgentStatus::Blocked: return PetVisualState::Blocked;
    case AgentStatus::Offline: return PetVisualState::Offline;
    case AgentStatus::Idle: return PetVisualState::Idle;
  }
  return PetVisualState::Idle;
}

uint16_t DeviceUi::codexStatusColor() const {
  switch (codexVisualState()) {
    case PetVisualState::Running:
    case PetVisualState::Thinking: return kAccent;
    case PetVisualState::NeedsInput: return kAccentWarm;
    case PetVisualState::Ready: return kGood;
    case PetVisualState::Blocked: return kBad;
    case PetVisualState::Offline: return kBad;
    case PetVisualState::Idle: return kTextDim;
  }
  return kTextDim;
}

const char* DeviceUi::codexStatusLabel(PetVisualState state) const {
  switch (state) {
    case PetVisualState::Offline: return "OFFLINE";
    case PetVisualState::Idle: return "IDLE";
    case PetVisualState::Thinking: return "THINKING";
    case PetVisualState::Running: return "RUNNING";
    case PetVisualState::NeedsInput: return "INPUT";
    case PetVisualState::Ready: return "READY";
    case PetVisualState::Blocked: return "BLOCK";
  }
  return "IDLE";
}

String DeviceUi::codexPreviewStatus() const {
  if (!pairing_.connected()) return "Mac offline";
  const AgentSession* agent = selectedAgent();
  if (!pairing_.agentOnline()) return "Waiting";
  if (!agent) return "No sessions";
  switch (agent->status) {
    case AgentStatus::Running:
      return agent->phase == AgentPhase::Tool ? "Running" : "Thinking";
    case AgentStatus::NeedsInput: return "Needs input";
    case AgentStatus::Ready: return "Ready";
    case AgentStatus::Blocked: return "Blocked";
    case AgentStatus::Offline: return "Offline";
    case AgentStatus::Idle: return "Idle";
  }
  return "Idle";
}

void DeviceUi::drawQuotaRow(int y, const char* label, int remaining,
                            AgentQuotaMode mode) {
  canvas_.setTextFont(1);
  canvas_.setTextSize(1);
  canvas_.setTextColor(mode == AgentQuotaMode::Unknown ? kTextDim : TFT_WHITE,
                       kPanel);
  canvas_.setCursor(kCodexContentX, y + 2);
  canvas_.print(label);
  constexpr int barX = 164;
  constexpr int barWidth = 68;
  constexpr int barHeight = 8;
  const int barY = y + (kCodexQuotaRowHeight - barHeight) / 2;
  canvas_.fillRoundRect(barX, barY, barWidth, barHeight, 2, kBackground);
  uint16_t borderColor = kTextDim;
  if (mode == AgentQuotaMode::Api) {
    // API-backed quotas are unmetered: a full static green rail communicates
    // healthy capacity without a rainbow animation or infinity glyph.
    const uint16_t railBody = blendRgb565(kBackground, kGood, 208);
    const uint16_t railCenter = blendRgb565(kGood, TFT_WHITE, 36);
    canvas_.fillRoundRect(barX + 1, barY + 1, barWidth - 2,
                          barHeight - 2, 1, railBody);
    canvas_.drawFastHLine(barX + 4, barY + barHeight / 2,
                          barWidth - 8, railCenter);
    borderColor = blendRgb565(kLine, kGood, 76);
  } else if (mode == AgentQuotaMode::Subscription && remaining >= 0) {
    const uint16_t quotaColor = remaining < 10
                                    ? kBad
                                    : (remaining < 30 ? TFT_YELLOW : kGood);
    const int clamped = min(100, max(0, remaining));
    // Keep a one-pixel warning marker at zero so an exhausted quota does not
    // become visually indistinguishable from an unknown/empty track.
    const int fill = max(1, (barWidth - 2) * clamped / 100);
    canvas_.fillRoundRect(barX + 1, barY + 1, fill, barHeight - 2, 1,
                          quotaColor);
    if (remaining < 30) {
      borderColor = blendRgb565(kLine, quotaColor, 92);
    }
  } else {
    canvas_.setTextColor(kTextDim, kBackground);
    canvas_.setTextDatum(middle_center);
    canvas_.drawString("--", barX + barWidth / 2, barY + barHeight / 2);
    canvas_.setTextDatum(top_left);
  }
  canvas_.drawRoundRect(barX, barY, barWidth, barHeight, 2, borderColor);
}

void DeviceUi::drawCodex() {
  const AgentSession* agent = selectedAgent();
  const PetVisualState visual = codexVisualState();
  const uint32_t now = millis();
  if (visual != codexEffectState_) {
    codexEffectState_ = visual;
    codexEffectStateStartedMs_ = now;
  }
  const uint16_t statusColor = codexStatusColor();
  String title = "Codex";
  String activity = pairing_.connected()
      ? "Waiting for Codex sessions" : "Codex Deck is offline";
  if (agent && pairing_.agentOnline()) {
    title = !agent->title.isEmpty() ? agent->title
                                   : (!agent->project.isEmpty() ? agent->project
                                                               : String("Codex"));
    activity = agent->activity;
  }

  // The whole display is one generated game scene. Only the text/quota area
  // on the right is a card; the pet stands directly on the background stage.
  drawCodexScene(visual);
  drawAngularPanel(kCodexRightX, kCodexPanelY, kCodexColumnWidth,
                   kCodexPanelHeight, false);

  pet_.draw(canvas_, visual, kCodexPetX, kCodexPetY, now, kCodexPetSize);
  drawCodexPlatformEffect(visual, now);
  drawKeyboardModeIcon(kCodexKeyboardX, kCodexKeyboardY);
  drawCodexSessionBadge(agentSelection_, pairing_.agentCount());
  drawBattery(75, 7, true);

  canvas_.fillRoundRect(kCodexContentX - 2, kCodexTitleY - 2,
                        kCodexContentWidth + 4, kCodexTitleHeight + 4, 5,
                        kBackground);
  canvas_.fillRoundRect(kCodexContentX - 2, kCodexActivityY - 1,
                        kCodexContentWidth + 4, kCodexActivityHeight + 3, 5,
                        kBackground);
  canvas_.drawRoundRect(kCodexContentX - 2, kCodexActivityY - 1,
                        kCodexContentWidth + 4, kCodexActivityHeight + 3, 5,
                        statusColor);
  drawCodexTitle(title);
  drawCodexActivity(activity);

  AgentQuotaMode quotaMode = pairing_.agentOnline()
                                 ? pairing_.agentQuota().mode
                                 : AgentQuotaMode::Unknown;
  drawQuotaRow(kCodexWeeklyY, "WEEKLY",
               pairing_.agentQuota().weeklyRemaining, quotaMode);
  drawQuotaRow(kCodexFiveHourY, "5H",
               pairing_.agentQuota().fiveHourRemaining, quotaMode);
}

void DeviceUi::drawMenuRow(int y, bool selected, const String& text,
                           const String& value) {
  const uint16_t background = selected ? kPanelSelected : kPanel;
  canvas_.fillRoundRect(4, y, kWidth - 8, 16, 3, background);
  if (selected) canvas_.drawRoundRect(4, y, kWidth - 8, 16, 3, kAccent);
  canvas_.setTextColor(selected ? TFT_WHITE : kTextDim, background);
  canvas_.setCursor(10, y + 4);
  canvas_.print(text);
  if (!value.isEmpty()) {
    const int width = canvas_.textWidth(value);
    canvas_.setCursor(kWidth - 10 - width, y + 4);
    canvas_.print(value);
  }
}

void DeviceUi::drawWifi() {
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setCursor(6, 24);
  canvas_.print(wifi_.scanning() ? "Scanning..." : "WiFi networks");
  const size_t count = wifi_.scanCount();
  const size_t first = listSelection_ >= 4 ? listSelection_ - 3 : 0;
  for (size_t row = 0; row < 4 && first + row < count; ++row) {
    const auto& item = wifi_.scanResult(first + row);
    const int y = 36 + row * 18;
    const bool selected = first + row == listSelection_;
    const uint16_t background = selected ? kPanelSelected : kPanel;
    drawMenuRow(y, selected, clipped(item.ssid, 18));
    drawWifiStrengthIcon(184, y + 2, item.rssi,
                         selected ? TFT_WHITE : kGood, background);
    if (item.saved) {
      const uint16_t color = selected ? TFT_WHITE : kTextDim;
      canvas_.drawRoundRect(204, y + 7, 9, 7, 1, color);
      canvas_.drawRect(206, y + 4, 5, 5, color);
    }
    if (wifi_.connected() && wifi_.currentSsid() == item.ssid) {
      canvas_.fillCircle(225, y + 8, 3, kGood);
    }
  }
  if (!wifi_.scanning() && count == 0) {
    canvas_.setCursor(6, 60);
    canvas_.print("No 2.4GHz networks found");
  }
  drawHint("Bksp forget  Tab rescan  Esc back");
}

void DeviceUi::drawPassword() {
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setCursor(8, 30);
  canvas_.print("Password for:");
  canvas_.setTextColor(kAccent, kBackground);
  canvas_.setCursor(8, 44);
  canvas_.print(clipped(pendingSsid_, 30));
  canvas_.drawRoundRect(6, 62, kWidth - 12, 26, 4, kTextDim);
  canvas_.setCursor(12, 71);
  canvas_.setTextColor(TFT_WHITE, kBackground);
  for (size_t i = 0; i < textEntry_.length(); ++i) canvas_.print('*');
  const bool shifted = M5Cardputer.Keyboard.keysState().shift;
  canvas_.setTextColor(shifted ? kAccent : kTextDim, kBackground);
  canvas_.setCursor(8, 98);
  canvas_.print(shifted ? "SHIFT: UPPERCASE / SYMBOLS"
                        : "Shift supports A-Z and symbols");
  drawHint("Enter connect  Esc cancel");
}

void DeviceUi::drawComputers() {
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setCursor(6, 24);
  canvas_.print("Paired Macs");
  const size_t total = pairing_.pairedCount() + 2;
  const size_t first = listSelection_ >= 4 ? listSelection_ - 3 : 0;
  for (size_t row = 0; row < 4 && first + row < total; ++row) {
    const size_t index = first + row;
    if (index < pairing_.pairedCount()) {
      String state = pairing_.pairedCurrent(index) ? "NOW" :
                     (pairing_.pairedOnline(index) ? "online" : "offline");
      drawMenuRow(36 + row * 18, index == listSelection_,
                  clipped(pairing_.paired(index).name, 16), state);
    } else if (index == pairing_.pairedCount()) {
      drawMenuRow(36 + row * 18, index == listSelection_, "+ Add computer");
    } else {
      drawMenuRow(36 + row * 18, index == listSelection_, "< Back");
    }
  }
  drawHint("Bksp delete  Esc back");
}

void DeviceUi::drawAddComputer() {
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setCursor(6, 24);
  canvas_.print("Nearby Macs");
  const size_t count = pairing_.discoveredCount();
  const size_t first = listSelection_ >= 4 ? listSelection_ - 3 : 0;
  for (size_t row = 0; row < 4 && first + row < count; ++row) {
    const auto& item = pairing_.discovered(first + row);
    drawMenuRow(36 + row * 18, first + row == listSelection_,
                clipped(item.name, 19), item.paired ? "paired" : "new");
  }
  if (count == 0) {
    canvas_.setCursor(6, 60);
    canvas_.print("Searching for Codex Deck...");
  }
  drawHint("Tab rescan  Esc back");
}

void DeviceUi::drawPairCode() {
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.setCursor(8, 28);
  canvas_.print("Enter the 6-digit code on the Mac");
  canvas_.setTextSize(3);
  canvas_.setTextColor(kAccent, kBackground);
  canvas_.setTextDatum(middle_center);
  String code = textEntry_;
  while (code.length() < 6) code += "-";
  canvas_.drawString(code, kWidth / 2, 70);
  canvas_.setTextDatum(top_left);
  canvas_.setTextSize(1);
  drawHint("Enter pair  Esc cancel");
}

void DeviceUi::drawBrightness() {
  canvas_.setTextDatum(middle_center);
  canvas_.setTextSize(3);
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.drawString(String(settings_.brightness), kWidth / 2, 53);
  canvas_.setTextSize(1);
  canvas_.setTextColor(kTextDim, kBackground);
  canvas_.drawString("Display brightness", kWidth / 2, 76);

  canvas_.drawRoundRect(28, 88, 184, 12, 3, kTextDim);
  const int fill = max(3, 178 * settings_.brightness / 255);
  canvas_.fillRoundRect(31, 91, fill, 6, 2, kAccent);
  const size_t selected = brightnessLevelIndex(settings_.brightness);
  for (size_t i = 0; i < sizeof(kBrightnessLevels); ++i) {
    canvas_.fillCircle(64 + i * 37, 110, 3,
                       i == selected ? kAccent : kPanel);
  }
  canvas_.setTextDatum(top_left);
  drawHint("Left/right adjust  Esc back");
}

void DeviceUi::drawScreenOff() {
  const String value = settings_.screenTimeoutSec == 0
      ? String("Never") : String(settings_.screenTimeoutSec) + " sec";
  canvas_.setTextDatum(middle_center);
  canvas_.setTextSize(3);
  canvas_.setTextColor(TFT_WHITE, kBackground);
  canvas_.drawString(value, kWidth / 2, 55);
  canvas_.setTextSize(1);
  canvas_.setTextColor(kTextDim, kBackground);
  canvas_.drawString("Automatic screen off", kWidth / 2, 78);

  const size_t selected = screenTimeoutIndex(settings_.screenTimeoutSec);
  static const char* labels[] = {"30", "60", "120", "300", "Never"};
  for (size_t i = 0; i < sizeof(labels) / sizeof(labels[0]); ++i) {
    const int x = 8 + i * 46;
    const bool active = i == selected;
    canvas_.fillRoundRect(x, 91, 40, 18, 4,
                          active ? kPanelSelected : kPanel);
    if (active) canvas_.drawRoundRect(x, 91, 40, 18, 4, kAccent);
    canvas_.setTextColor(active ? TFT_WHITE : kTextDim,
                         active ? kPanelSelected : kPanel);
    canvas_.drawString(labels[i], x + 20, 100);
  }
  canvas_.setTextDatum(top_left);
  drawHint("Left/right adjust  Esc back");
}

String DeviceUi::clipped(const String& value, size_t length) const {
  if (value.length() <= length) return value;
  if (length < 2) return value.substring(0, length);
  return value.substring(0, length - 1) + "~";
}

}  // namespace cardbridge
