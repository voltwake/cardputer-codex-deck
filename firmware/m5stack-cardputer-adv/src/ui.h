#pragma once

#include <M5Cardputer.h>

#include "audio_tx.h"
#include "key_tx.h"
#include "models.h"
#include "pairing.h"
#include "pet_renderer.h"
#include "settings_store.h"
#include "wifi_mgr.h"

namespace cardbridge {

// v4 UX: one keyboard, two masters, made explicit.
//  - Remote mode: every key goes to the Mac while the current page remains
//    visible; a keyboard icon in the status bar shows that forwarding is on.
//  - Local mode: every key drives this UI with natural bindings
//    (;.,/ + ijkl arrows, Enter, Esc/Backspace) — no Fn chords.
//  - BtnA (the physical button beside the screen) toggles modes; it is not
//    part of the keyboard so it can never collide with typing.
// All rendering goes through an off-screen canvas to kill flicker.
enum class UiMode : uint8_t { Local, Remote };

class DeviceUi {
 public:
  DeviceUi(SettingsStore& store, WifiManager& wifi, PairingManager& pairing,
           AudioTransmitter& audio, KeyTransmitter& keys,
           DeviceSettings& settings)
      : store_(store),
        wifi_(wifi),
        pairing_(pairing),
        audio_(audio),
        keys_(keys),
        settings_(settings) {}

  void begin();
  void tick();
  bool consumesKeyboard() const { return consumesKeyboard_; }
  // Exposed so the serial console can drive/inspect the mode during bring-up.
  void toggleMode() { setMode(mode_ == UiMode::Remote ? UiMode::Local : UiMode::Remote); }
  void showCodex();
  const char* modeName() const { return mode_ == UiMode::Remote ? "remote" : "local"; }

 private:
  enum class Page : uint8_t {
    Main,
    Codex,
    Wifi,
    WifiPassword,
    Computers,
    AddComputer,
    PairCode,
    Brightness,
    ScreenOff,
  };

  // input
  bool pressed(char character) const;
  bool navUp() const;
  bool navDown() const;
  bool navLeft() const;
  bool navRight() const;
  bool enterPressed() const;
  bool escapePressed() const;
  bool backspacePressed() const;
  bool backPressed() const;
  void handleInput();
  void handleMain();
  void handleCodex();
  void handleWifi();
  void handlePassword();
  void handleComputers();
  void handleAddComputer();
  void handlePairCode();
  void handleBrightness();
  void handleScreenOff();
  void appendTypedText(String& destination, size_t maxLength, bool digitsOnly);
  void setPage(Page page);
  void setMode(UiMode mode);
  void noteActivity();
  void wakeScreen();
  void updateScreenPower();
  void updateBatteryState(bool force = false);
  void resetBatteryTrend();
  uint32_t renderIntervalMs() const;

  // drawing (all onto canvas_)
  void render();
  void drawStatusBar();
  String statusBarTitle() const;
  void drawScrollingTitle(const String& title);
  void drawCodexTitle(const String& title);
  void drawCodexSessionBadge(size_t index, size_t count);
  void drawCodexActivity(const String& activity);
  void prepareCodexActivity(const String& activity);
  String fitWithEllipsis(String text, int width, bool force);
  void drawKeyboardModeIcon(int x, int y);
  void drawGameBackground();
  void drawAngularPanel(int x, int y, int width, int height, bool selected);
  void drawWorkshopStage(int x, int y, int width, int height,
                         PetVisualState state);
  void drawWorkshopMonitor(PetVisualState state, uint32_t now);
  void drawWorkshopDataConduit(PetVisualState state, uint32_t now);
  void drawCodexScene(PetVisualState state);
  void drawCodexPlatformEffect(PetVisualState state, uint32_t now);
  void drawHomeStatusLine(int x, int y, int width, PetVisualState state);
  void drawMain();
  void drawCodex();
  void drawQuotaRow(int y, const char* label, int remaining,
                    AgentQuotaMode mode);
  void drawWifi();
  void drawPassword();
  void drawComputers();
  void drawAddComputer();
  void drawPairCode();
  void drawBrightness();
  void drawScreenOff();
  void drawHomeSettingRow(int y, uint8_t index, const String& text,
                          const String& value);
  void drawMenuRow(int y, bool selected, const String& text,
                   const String& value = String());
  void drawHint(const String& text);
  void drawWifiBars(int x, int y, int rssi, bool connected);
  void drawWifiStrengthIcon(int x, int y, int rssi, uint16_t active,
                            uint16_t inactive);
  void drawBattery(int x, int y, bool compact = false);
  String clipped(const String& value, size_t length) const;
  const AgentSession* selectedAgent() const;
  PetVisualState codexVisualState() const;
  uint16_t codexStatusColor() const;
  const char* codexStatusLabel(PetVisualState state) const;
  String codexPreviewStatus() const;

  SettingsStore& store_;
  WifiManager& wifi_;
  PairingManager& pairing_;
  AudioTransmitter& audio_;
  KeyTransmitter& keys_;
  DeviceSettings& settings_;

  M5Canvas canvas_{&M5Cardputer.Display};
  PetRenderer pet_;
  // External BFFfont lets the canvas switch between its normal bitmap fonts
  // and our anti-aliased Chinese face without unloading the runtime font.
  lgfx::PointerWrapper uiFontData_;
  lgfx::BFFfont uiFont_;
  const lgfx::IFont* uiFontFace_ = nullptr;
  UiMode mode_ = UiMode::Local;
  Page page_ = Page::Main;
  uint8_t mainSelection_ = 0;
  uint8_t homeSettingSelection_ = 0;
  size_t listSelection_ = 0;
  size_t agentSelection_ = 0;
  String selectedAgentId_;
  String lastAgentFocusId_;
  uint32_t lastAgentFocusSeq_ = 0;
  uint32_t lastAgentSnapshotSeq_ = 0;
  LinkState lastLinkState_ = LinkState::Offline;
  bool lastWifiConnected_ = false;
  PetVisualState codexEffectState_ = PetVisualState::Idle;
  uint32_t codexEffectStateStartedMs_ = 0;
  String marqueeTitle_;
  uint32_t marqueeStartedMs_ = 0;
  String wrappedActivity_;
  String activityLines_[4];
  uint8_t activityLineCount_ = 0;
  String pendingSsid_;
  String textEntry_;
  bool screenOff_ = false;
  bool screenDimmed_ = false;
  bool consumesKeyboard_ = false;
  bool suppressUntilRelease_ = false;
  bool renderRequested_ = true;
  bool batteryCharging_ = false;
  bool usbPowerPresent_ = false;
  int8_t batteryLevel_ = -1;
  int16_t batteryVoltageMv_ = 0;
  int16_t batteryTrendBaselineMv_ = 0;
  uint32_t lastActivityMs_ = 0;
  uint32_t lastRenderMs_ = 0;
  uint32_t lastComputerScanMs_ = 0;
  uint32_t lastBatterySampleMs_ = 0;
  uint32_t batteryTrendStartedMs_ = 0;
  uint32_t inferredChargingUntilMs_ = 0;
};

}  // namespace cardbridge
