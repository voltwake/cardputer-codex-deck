#include "serial_console.h"

#include "generated_version.h"

namespace cardbridge {
namespace {

const char* linkStateName(LinkState state) {
  switch (state) {
    case LinkState::Offline: return "offline";
    case LinkState::Discovering: return "discovering";
    case LinkState::Connecting: return "connecting";
    case LinkState::AwaitingPairCode: return "awaiting_pair_code";
    case LinkState::Authenticating: return "authenticating";
    case LinkState::Connected: return "connected";
    case LinkState::Incompatible: return "incompatible";
  }
  return "offline";
}

const char* agentStatusName(AgentStatus status) {
  switch (status) {
    case AgentStatus::Offline: return "offline";
    case AgentStatus::Idle: return "idle";
    case AgentStatus::Running: return "running";
    case AgentStatus::NeedsInput: return "needs_input";
    case AgentStatus::Ready: return "ready";
    case AgentStatus::Blocked: return "blocked";
  }
  return "idle";
}

const char* agentPhaseName(AgentPhase phase) {
  switch (phase) {
    case AgentPhase::None: return "none";
    case AgentPhase::Thinking: return "thinking";
    case AgentPhase::Tool: return "tool";
  }
  return "none";
}

}  // namespace

void SerialConsole::tick() {
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (!buffer_.isEmpty()) {
        handle(buffer_);
        buffer_.clear();
      }
    } else if (buffer_.length() < 200) {
      buffer_ += c;
    }
  }
}

void SerialConsole::handle(const String& line) {
  String command = line;
  command.trim();
  const int space = command.indexOf(' ');
  const String verb = space < 0 ? command : command.substring(0, space);
  const String rest = space < 0 ? String() : command.substring(space + 1);

  if (verb == "status") {
    printStatus();
  } else if (verb == "mode") {
    ui_.toggleMode();
    Serial.printf("[console] mode -> %s\n", ui_.modeName());
  } else if (verb == "audio") {
    audio_.printDebug();
  } else if (verb == "scan") {
    wifi_.startScan();
    Serial.println("[console] scan queued; run 'wifis' for results");
  } else if (verb == "wifis") {
    for (size_t i = 0; i < wifi_.scanCount(); ++i) {
      const auto& network = wifi_.scanResult(i);
      Serial.printf("[wifis] %u \"%s\" rssi=%d%s%s\n", i,
                    network.ssid.c_str(), network.rssi,
                    network.encrypted ? " enc" : "",
                    network.saved ? " saved" : "");
    }
    Serial.printf("[wifis] total=%u scanning=%d\n", wifi_.scanCount(),
                  wifi_.scanning());
  } else if (verb == "wifi") {
    const int separator = rest.indexOf(' ');
    if (separator <= 0) {
      Serial.println("[console] usage: wifi <ssid> <password>");
      return;
    }
    const String ssid = rest.substring(0, separator);
    const String password = rest.substring(separator + 1);
    const bool ok = wifi_.addAndConnect(ssid, password);
    Serial.printf("[console] wifi add \"%s\" -> %s\n", ssid.c_str(),
                  ok ? "connecting" : "FAILED");
  } else if (verb == "forget") {
    Serial.printf("[console] forget -> %d\n", wifi_.forget(rest));
  } else if (verb == "computers") {
    printComputers();
  } else if (verb == "agents") {
    const AgentQuota& quota = pairing_.agentQuota();
    const char* quotaMode = quota.mode == AgentQuotaMode::Subscription
                                ? "subscription"
                                : quota.mode == AgentQuotaMode::Api ? "api" : "unknown";
    Serial.printf(
        "[agents] online=%d quota_mode=%s count=%u focus=%s weekly=%d "
        "five_hour=%d\n",
        pairing_.agentOnline(), quotaMode, pairing_.agentCount(),
        pairing_.agentFocusId().c_str(), quota.weeklyRemaining,
        quota.fiveHourRemaining);
    for (size_t i = 0; i < pairing_.agentCount(); ++i) {
      const AgentSession& agent = pairing_.agent(i);
      Serial.printf("[agents] %u %s/%s unread=%d project=\"%s\" title=\"%s\" activity=\"%s\"\n",
                    i, agentStatusName(agent.status), agentPhaseName(agent.phase), agent.unread,
                    agent.project.c_str(), agent.title.c_str(),
                    agent.activity.c_str());
    }
  } else if (verb == "page" && rest == "codex") {
    ui_.showCodex();
    Serial.println("[console] page -> codex");
  } else if (verb == "discover") {
    pairing_.requestDiscovery();
    Serial.println("[console] discovery requested");
  } else if (verb == "connect") {
    const size_t index = static_cast<size_t>(rest.toInt());
    Serial.printf("[console] connect %u -> %d\n", index,
                  pairing_.connectToDiscovered(index));
  } else if (verb == "pair") {
    Serial.printf("[console] pair -> %d\n", pairing_.submitPairCode(rest));
  } else if (verb == "key") {
    // key <name> [cmd|shift|alt|ctrl,...]  e.g. "key a", "key c cmd"
    String name = rest;
    String modifiers;
    const int separator = rest.indexOf(' ');
    if (separator > 0) {
      name = rest.substring(0, separator);
      modifiers = rest.substring(separator + 1);
    }
    const bool cmd = modifiers.indexOf("cmd") >= 0;
    const bool shift = modifiers.indexOf("shift") >= 0;
    const bool alt = modifiers.indexOf("alt") >= 0;
    const bool ctrl = modifiers.indexOf("ctrl") >= 0;
    const bool down = pairing_.sendKey(name.c_str(), "down", cmd, shift, alt, ctrl);
    const bool up = pairing_.sendKey(name.c_str(), "up", cmd, shift, alt, ctrl);
    Serial.printf("[console] key %s -> down=%d up=%d\n", name.c_str(), down, up);
  } else if (verb == "dump") {
    audio_.dumpRaw();
  } else if (verb == "pull") {
    // pull u|d|n — set GPIO46 internal pull and sample: distinguishes a
    // floating line (follows the pull) from a codec-driven line (ignores it).
    if (rest == "u") gpio_set_pull_mode(GPIO_NUM_46, GPIO_PULLUP_ONLY);
    else if (rest == "d") gpio_set_pull_mode(GPIO_NUM_46, GPIO_PULLDOWN_ONLY);
    else gpio_set_pull_mode(GPIO_NUM_46, GPIO_FLOATING);
    uint32_t highs = 0;
    for (uint32_t i = 0; i < 20000; ++i) highs += gpio_get_level(GPIO_NUM_46);
    Serial.printf("[pull] %s -> GPIO46 high %.1f%%\n", rest.c_str(),
                  100.0 * highs / 20000);
  } else if (verb == "pins") {
    // Sample the I2S pads rapidly: a driven clock/data line shows mixed
    // levels; a stuck line shows 0% or 100%.
    const int pins[] = {41, 43, 46, 42};
    for (int pin : pins) {
      uint32_t highs = 0;
      const uint32_t samples = 20000;
      for (uint32_t i = 0; i < samples; ++i) {
        highs += gpio_get_level(static_cast<gpio_num_t>(pin));
      }
      Serial.printf("[pins] GPIO%d high %lu/%lu (%.1f%%)\n", pin,
                    (unsigned long)highs, (unsigned long)samples,
                    100.0 * highs / samples);
    }
  } else if (verb == "wreg") {
    // wreg <hexreg> <hexval> — live ES8311 register poke for bring-up.
    const int separator = rest.indexOf(' ');
    if (separator > 0) {
      const uint8_t reg = strtoul(rest.substring(0, separator).c_str(), nullptr, 16);
      const uint8_t value = strtoul(rest.substring(separator + 1).c_str(), nullptr, 16);
      const bool ok = M5.In_I2C.writeRegister8(0x18, reg, value, 100000);
      Serial.printf("[wreg] 0x%02X <= 0x%02X %s\n", reg, value, ok ? "ok" : "FAILED");
    }
  } else if (verb == "rreg") {
    const uint8_t reg = strtoul(rest.c_str(), nullptr, 16);
    uint8_t value = 0;
    M5.In_I2C.readRegister(0x18, reg, &value, 1, 100000);
    Serial.printf("[rreg] 0x%02X = 0x%02X\n", reg, value);
  } else if (verb == "es8311") {
    // Dump codec registers 0x00-0x1D to verify the init writes landed.
    for (uint8_t reg = 0x00; reg <= 0x1D; ++reg) {
      uint8_t value = 0;
      const bool ok = M5.In_I2C.readRegister(0x18, reg, &value, 1, 100000);
      Serial.printf("[es8311] 0x%02X = 0x%02X%s\n", reg, value, ok ? "" : " (read failed)");
    }
  } else if (verb == "i2c") {
    for (uint8_t address = 0x08; address < 0x78; ++address) {
      if (M5.In_I2C.scanID(address)) Serial.printf("[i2c] found 0x%02X\n", address);
    }
    Serial.println("[i2c] scan done");
  } else if (verb == "beep") {
    // Mic must be muted first ('mute on'): Speaker and Mic share the codec.
    M5Cardputer.Speaker.begin();
    M5Cardputer.Speaker.setVolume(180);
    M5Cardputer.Speaker.tone(2000, 500);
    delay(600);
    M5Cardputer.Speaker.end();
    Serial.println("[console] beep done");
  } else if (verb == "mute") {
    settings_.micMuted = rest == "on";
    audio_.setMuted(settings_.micMuted);
    store_.saveSettings(settings_);
    Serial.printf("[console] mic muted=%d\n", settings_.micMuted);
  } else if (verb == "disconnect") {
    pairing_.disconnect(true);
    Serial.println("[console] disconnected");
  } else if (verb == "help") {
    Serial.println(
        "[console] status | scan | wifis | wifi <ssid> <pw> | forget <ssid> | "
        "computers | discover | connect <n> | pair <code> | key <k> [mods] | "
        "agents | page codex | mute on|off | disconnect");
  } else {
    Serial.printf("[console] unknown command \"%s\" (try 'help')\n",
                  verb.c_str());
  }
}

void SerialConsole::printStatus() {
  const auto board = M5.getBoard();
  const char* boardName =
      board == m5::board_t::board_M5CardputerADV ? "CardputerADV"
      : board == m5::board_t::board_M5Cardputer  ? "Cardputer"
                                                 : "other";
  Serial.printf("[board] %s (%d) ui_mode=%s btnA=%d\n", boardName,
                static_cast<int>(board), ui_.modeName(),
                M5Cardputer.BtnA.isPressed());
  Serial.printf(
      "[status] wifi=%d ssid=\"%s\" ip=%s rssi=%d link=%s mac=\"%s\" "
      "paired=%u mic_active=%d muted=%d level=%u dropped=%u heap=%u "
      "fw=%s/%lu proto=%u.%u "
      "bridge=%s/%lu bridge_proto=%u.%u incompat=\"%s\" required_fw=%s\n",
      wifi_.connected(), wifi_.currentSsid().c_str(),
      wifi_.localIp().toString().c_str(), wifi_.rssi(),
      linkStateName(pairing_.state()),
      pairing_.connectedName().c_str(), pairing_.pairedCount(),
      audio_.active(), audio_.muted(), audio_.level(), audio_.droppedFrames(),
      ESP.getFreeHeap(), kFirmwareVersion,
      static_cast<unsigned long>(kFirmwareBuild), kDeviceProtocolMajor,
      kDeviceProtocolMinor, pairing_.bridgeVersion().c_str(),
      static_cast<unsigned long>(pairing_.bridgeBuild()),
      pairing_.bridgeProtocolMajor(), pairing_.bridgeProtocolMinor(),
      pairing_.compatibilityReason().c_str(), pairing_.requiredFirmware().c_str());
}

void SerialConsole::printComputers() {
  for (size_t i = 0; i < pairing_.discoveredCount(); ++i) {
    const auto& mac = pairing_.discovered(i);
    Serial.printf("[computers] discovered %u \"%s\" %s:%u%s\n", i,
                  mac.name.c_str(), mac.ip.toString().c_str(), mac.port,
                  mac.paired ? " paired" : "");
  }
  for (size_t i = 0; i < pairing_.pairedCount(); ++i) {
    Serial.printf("[computers] paired %u \"%s\" id=%s%s\n", i,
                  pairing_.paired(i).name.c_str(),
                  pairing_.paired(i).id.c_str(),
                  pairing_.pairedCurrent(i) ? " CURRENT" : "");
  }
}

}  // namespace cardbridge
