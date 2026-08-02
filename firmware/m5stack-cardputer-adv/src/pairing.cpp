#include "pairing.h"

#include <cstring>
#include <new>

#include "generated_version.h"

namespace cardbridge {
namespace {

constexpr uint32_t kDiscoveryTimeoutMs = 3000;

bool deadlineReached(uint32_t deadline) {
  return static_cast<int32_t>(millis() - deadline) >= 0;
}

String resultTxt(const mdns_result_t* result, const char* key) {
  if (!result || !key) return String();
  for (size_t i = 0; i < result->txt_count; ++i) {
    if (result->txt[i].key && strcmp(result->txt[i].key, key) == 0) {
      return String(result->txt[i].value ? result->txt[i].value : "");
    }
  }
  return String();
}

IPAddress resultIpv4(const mdns_result_t* result) {
  if (!result) return IPAddress();
  for (mdns_ip_addr_t* address = result->addr; address; address = address->next) {
    if (address->addr.type == MDNS_IP_PROTOCOL_V4) {
      return IPAddress(address->addr.u_addr.ip4.addr);
    }
  }
  return IPAddress();
}

}  // namespace

void PairingManager::begin(DeviceSettings* settings) {
  settings_ = settings;
  pairedCount_ = store_.loadPairedMacs(paired_, kMaxPairedMacs);
  deviceId_ = WiFi.macAddress();
  deviceId_.replace(":", "");
  deviceId_.toLowerCase();
  incoming_.reserve(4096);
  connectResultQueue_ = xQueueCreate(1, sizeof(ConnectResult));
  if (!connectResultQueue_) {
    Serial.println("[pairing] failed to create connection result queue");
  }
  if (settings_ && !settings_->lastMacId.isEmpty()) targetId_ = settings_->lastMacId;
}

void PairingManager::tick() {
  // Both operations used to block this function (and therefore the keyboard/UI
  // loop) for 1.5-3 seconds. They are now polled without waiting.
  pollDiscovery();
  pollConnectionAttempt();

  if (!wifi_.connected()) {
    cancelConnectionAttempt();
    state_ = LinkState::Offline;
    agentOnline_ = false;
    setAudioReady(false);
    discoveredCount_ = 0;
    discoveryRequested_ = false;
    rediscoveryRequired_ = true;
    // An async mDNS search owns memory inside the mDNS service until its
    // timeout. Poll it to completion before stopping mDNS.
    if (mdnsStarted_ && !discoverySearch_) {
      MDNS.end();
      mdnsStarted_ = false;
      nextConnectMs_ = 0;
    }
    return;
  }

  if (!mdnsStarted_) {
    mdnsStarted_ = MDNS.begin((String("cardputer-") + deviceId_.substring(6)).c_str());
    if (mdnsStarted_) {
      discoveryRequested_ = true;
      rediscoveryRequired_ = true;
      nextConnectMs_ = 0;
    }
  }

  const bool autoReconnect = !manualDisconnect_ && !targetId_.isEmpty();
  if (discoveryRequested_ && !connectInFlight_) {
    startDiscovery(autoReconnect && deadlineReached(nextConnectMs_));
  }

  // NetworkClient::connect() runs on a worker while this task keeps servicing
  // input. No other code may touch client_ until the result is delivered.
  if (connectInFlight_) return;

  if (client_.connected()) {
    readIncoming();
    const uint32_t now = millis();
    if (now - lastHeartbeatMs_ >= kHeartbeatMs) {
      StaticJsonDocument<256> ping;
      ping["t"] = "ping";
      if (!sendDocument(ping) || ++missedPongs_ >= kHeartbeatMissLimit) {
        connectionLost();
        return;
      }
      lastHeartbeatMs_ = now;
    }
    return;
  }

  if (state_ == LinkState::Connected || state_ == LinkState::Authenticating ||
      state_ == LinkState::AwaitingPairCode) {
    connectionLost();
  }

  if (autoReconnect && !discoverySearch_ && deadlineReached(nextConnectMs_)) {
    int found = discoveredIndexById(targetId_);
    if (found >= 0 && !rediscoveryRequired_) {
      targetIp_ = discovered_[found].ip;
      targetPort_ = discovered_[found].port;
      targetName_ = discovered_[found].name;
      attemptConnection();
    } else {
      startDiscovery(true);
    }
  }
}

void PairingManager::requestDiscovery() {
  if (wifi_.connected()) discoveryRequested_ = true;
}

bool PairingManager::startDiscovery(bool forReconnect) {
  if (!wifi_.connected() || !mdnsStarted_ || connectInFlight_) return false;
  if (discoverySearch_) {
    if (forReconnect) discoveryForReconnect_ = true;
    return true;
  }
  discoveryRequested_ = false;
  discoveryForReconnect_ = forReconnect;
  state_ = client_.connected() ? state_ : LinkState::Discovering;
  discoverySearch_ = mdns_query_async_new(
      nullptr, "_cardbridge", "_tcp", MDNS_TYPE_PTR, kDiscoveryTimeoutMs,
      kMaxDiscoveredMacs, nullptr);
  if (!discoverySearch_) {
    discoveryForReconnect_ = false;
    if (!client_.connected()) state_ = LinkState::Offline;
    if (forReconnect) scheduleReconnect();
    Serial.println("[pairing] failed to start async mDNS discovery");
    return false;
  }
  return true;
}

void PairingManager::pollDiscovery() {
  if (!discoverySearch_) return;
  mdns_result_t* results = nullptr;
  if (!mdns_query_async_get_results(discoverySearch_, 0, &results, nullptr)) {
    return;
  }

  mdns_search_once_t* finishedSearch = discoverySearch_;
  discoverySearch_ = nullptr;
  mdns_query_async_delete(finishedSearch);
  const bool forReconnect = discoveryForReconnect_;
  discoveryForReconnect_ = false;

  if (!wifi_.connected()) {
    discoveredCount_ = 0;
    rediscoveryRequired_ = true;
    if (results) mdns_query_results_free(results);
    return;
  }

  collectDiscoveryResults(results);
  if (results) mdns_query_results_free(results);
  if (!client_.connected()) state_ = LinkState::Offline;

  const int found = targetId_.isEmpty() ? -1 : discoveredIndexById(targetId_);
  rediscoveryRequired_ = !targetId_.isEmpty() && found < 0;
  if (!forReconnect || manualDisconnect_ || targetId_.isEmpty()) return;
  if (found < 0) {
    scheduleReconnect();
    return;
  }
  targetIp_ = discovered_[found].ip;
  targetPort_ = discovered_[found].port;
  targetName_ = discovered_[found].name;
  attemptConnection();
}

void PairingManager::collectDiscoveryResults(mdns_result_t* results) {
  discoveredCount_ = 0;
  for (mdns_result_t* result = results;
       result && discoveredCount_ < kMaxDiscoveredMacs; result = result->next) {
    DiscoveredMac mac;
    mac.id = resultTxt(result, "id");
    mac.name = resultTxt(result, "name");
    if (mac.id.isEmpty() && result->hostname) mac.id = result->hostname;
    if (mac.name.isEmpty() && result->hostname) mac.name = result->hostname;
    mac.ip = resultIpv4(result);
    // The ESP32 mDNS resolver sometimes returns the service without its A
    // record (0.0.0.0). Keeping such an entry would wedge the reconnect
    // machine on an unconnectable address; drop it and let a later
    // discovery sweep resolve it properly.
    if (mac.ip == IPAddress()) continue;
    mac.port = result->port ? result->port : kControlPort;
    mac.paired = pairedIndexById(mac.id) >= 0;
    discovered_[discoveredCount_++] = mac;
  }
}

bool PairingManager::connectToDiscovered(size_t index) {
  if (index >= discoveredCount_) return false;
  disconnect(false);
  manualDisconnect_ = false;
  targetId_ = discovered_[index].id;
  targetName_ = discovered_[index].name;
  targetIp_ = discovered_[index].ip;
  targetPort_ = discovered_[index].port;
  const int pairedIndex = pairedIndexById(targetId_);
  targetToken_ = pairedIndex >= 0 ? paired_[pairedIndex].token : String();
  nextConnectMs_ = 0;
  reconnectDelayMs_ = kReconnectMinMs;
  rediscoveryRequired_ = false;
  compatibilityReason_.clear();
  requiredFirmware_.clear();
  return true;
}

bool PairingManager::connectToPaired(size_t index) {
  if (index >= pairedCount_) return false;
  const int discoveredIndex = discoveredIndexById(paired_[index].id);
  if (discoveredIndex < 0) return false;
  return connectToDiscovered(static_cast<size_t>(discoveredIndex));
}

void PairingManager::attemptConnection() {
  if (connectInFlight_) return;
  if (targetIp_ == IPAddress()) {
    // No usable address yet — back off and re-discover instead of silently
    // spinning against 0.0.0.0.
    scheduleReconnect();
    return;
  }
  if (!connectResultQueue_) {
    Serial.println("[pairing] connection unavailable: no result queue");
    scheduleReconnect();
    return;
  }
  state_ = LinkState::Connecting;
  client_.stop();  // Enforce exactly one active Mac connection.
  auto* context = new (std::nothrow) ConnectTaskContext{
      this, targetIp_, targetPort_, ++connectGeneration_};
  if (!context) {
    scheduleReconnect();
    state_ = LinkState::Offline;
    return;
  }
  cancelConnect_ = false;
  connectInFlight_ = true;
  if (xTaskCreatePinnedToCore(connectTaskEntry, "mac_connect", 4096, context, 1,
                              nullptr, 0) != pdPASS) {
    connectInFlight_ = false;
    delete context;
    scheduleReconnect();
    state_ = LinkState::Offline;
  }
}

void PairingManager::connectTaskEntry(void* argument) {
  auto* context = static_cast<ConnectTaskContext*>(argument);
  PairingManager* manager = context->manager;
  const ConnectResult result{
      context->generation,
      manager->client_.connect(context->ip, context->port, 1500) != 0,
  };
  xQueueOverwrite(manager->connectResultQueue_, &result);
  delete context;
  vTaskDelete(nullptr);
}

void PairingManager::pollConnectionAttempt() {
  if (!connectInFlight_ || !connectResultQueue_) return;
  ConnectResult result{};
  if (xQueueReceive(connectResultQueue_, &result, 0) != pdPASS) return;
  connectInFlight_ = false;
  const bool cancelled = cancelConnect_ || result.generation != connectGeneration_ ||
                         !wifi_.connected();
  cancelConnect_ = false;
  if (cancelled) {
    if (result.connected) client_.stop();
    state_ = LinkState::Offline;
    return;
  }
  if (!result.connected) {
    scheduleReconnect();
    state_ = LinkState::Offline;
    return;
  }
  client_.setNoDelay(true);
  client_.setTimeout(1);
  incoming_.clear();
  missedPongs_ = 0;
  lastHeartbeatMs_ = millis();
  sendHello();
}

void PairingManager::cancelConnectionAttempt() {
  if (connectInFlight_) {
    cancelConnect_ = true;
  } else if (client_.connected()) {
    client_.stop();
  }
}

void PairingManager::sendHello() {
  const int index = pairedIndexById(targetId_);
  targetToken_ = index >= 0 ? paired_[index].token : String();
  StaticJsonDocument<768> hello;
  hello["t"] = "hello";
  hello["dev_id"] = deviceId_;
  if (targetToken_.isEmpty()) {
    hello["token"] = nullptr;
  } else {
    hello["token"] = targetToken_;
  }
  JsonObject device = hello.createNestedObject("device");
  device["model"] = "cardputer-adv";
  device["firmware"] = kFirmwareVersion;
  device["build"] = kFirmwareBuild;
  JsonObject protocol = hello.createNestedObject("protocol");
  protocol["major"] = kDeviceProtocolMajor;
  protocol["minor"] = kDeviceProtocolMinor;
  JsonArray capabilities = hello.createNestedArray("capabilities");
  for (size_t i = 0; i < kDeviceCapabilityCount; ++i) {
    capabilities.add(kDeviceCapabilities[i]);
  }
  if (!sendDocument(hello)) {
    connectionLost();
  } else {
    state_ = targetToken_.isEmpty() ? LinkState::AwaitingPairCode
                                    : LinkState::Authenticating;
  }
}

bool PairingManager::submitPairCode(const String& sixDigits) {
  if (!client_.connected() || sixDigits.length() != 6) return false;
  for (char c : sixDigits) {
    if (!isDigit(c)) return false;
  }
  StaticJsonDocument<128> pair;
  pair["t"] = "pair";
  pair["code"] = sixDigits;
  state_ = LinkState::Authenticating;
  return sendDocument(pair);
}

bool PairingManager::sendKey(const char* key, const char* action, bool cmd,
                             bool shift, bool option, bool control) {
  if (!connected() || !client_.connected()) return false;
  StaticJsonDocument<384> document;
  document["t"] = "key";
  document["k"] = key;
  document["a"] = action;
  JsonArray modifiers = document.createNestedArray("m");
  if (cmd) modifiers.add("cmd");
  if (shift) modifiers.add("shift");
  if (option) modifiers.add("alt");
  if (control) modifiers.add("ctrl");
  return sendDocument(document);
}

bool PairingManager::sendAgentAck(const String& sessionId) {
  if (!connected() || sessionId.isEmpty()) return false;
  StaticJsonDocument<320> document;
  document["t"] = "agent_ack";
  document["id"] = sessionId;
  return sendDocument(document);
}

bool PairingManager::sendDocument(JsonDocument& document) {
  if (!client_.connected()) return false;
  if (state_ == LinkState::Connected && targetToken_.length() == 64 &&
      !document["token"].is<String>()) {
    document["token"] = targetToken_;
  }
  if (document.overflowed()) return false;
  char line[512];
  const size_t jsonLength = measureJson(document);
  if (jsonLength + 1 > sizeof(line)) return false;
  const size_t written = serializeJson(document, line, sizeof(line));
  line[written] = '\n';
  return client_.write(reinterpret_cast<const uint8_t*>(line), written + 1) ==
         written + 1;
}

void PairingManager::readIncoming() {
  while (client_.available()) {
    const char c = static_cast<char>(client_.read());
    if (c == '\n') {
      if (!incoming_.isEmpty()) handleLine(incoming_);
      incoming_.clear();
    } else if (c != '\r') {
      if (incoming_.length() < 4096) {
        incoming_ += c;
      } else {
        incoming_.clear();  // Reject oversized lines without losing the link.
      }
    }
  }
}

void PairingManager::handleLine(const String& line) {
  incomingDocument_.clear();
  if (deserializeJson(incomingDocument_, line) != DeserializationError::Ok) return;
  const String type = incomingDocument_["t"].as<String>();
  if (state_ == LinkState::Connected &&
      (type == "ping" || type == "pong" || type == "agent_status" ||
       type == "agent_list") &&
      incomingDocument_["token"].as<String>() != targetToken_) {
    return;
  }
  if (type == "pong") {
    missedPongs_ = 0;
    if (incomingDocument_["audio_received"].is<uint32_t>()) {
      const uint32_t received = incomingDocument_["audio_received"].as<uint32_t>();
      const bool outputReady = incomingDocument_["audio_output_ready"] | false;
      portENTER_CRITICAL(&audioMux_);
      audioStatusSeen_ = true;
      audioOutputReady_ = outputReady;
      audioReceived_ = received;
      audioStatusMs_ = millis();
      portEXIT_CRITICAL(&audioMux_);
    }
    return;
  }
  if (type == "ping") {
    StaticJsonDocument<256> pong;
    pong["t"] = "pong";
    sendDocument(pong);
    return;
  }
  if (type == "upgrade_required") {
    compatibilityReason_ = incomingDocument_["reason"] | "version_mismatch";
    requiredFirmware_ = incomingDocument_["required"]["min_firmware"] | "";
    parseBridgeMetadata(incomingDocument_);
    client_.stop();
    incoming_.clear();
    connectedName_ = targetName_;
    state_ = LinkState::Incompatible;
    agentOnline_ = false;
    setAudioReady(false);
    manualDisconnect_ = true;
    missedPongs_ = 0;
    return;
  }
  if (type == "pair_required") {
    parseBridgeMetadata(incomingDocument_);
    targetName_ = incomingDocument_["mac_name"] | targetName_;
    connectedName_ = targetName_;
    state_ = LinkState::AwaitingPairCode;
    return;
  }
  if (type == "pair_error") {
    state_ = LinkState::AwaitingPairCode;
    return;
  }
  if (type == "paired") {
    parseBridgeMetadata(incomingDocument_);
    const String token = incomingDocument_["token"].as<String>();
    if (token.length() < 64) {
      connectionLost();
      return;
    }
    targetToken_ = token;
    int index = pairedIndexById(targetId_);
    if (index < 0) {
      if (pairedCount_ >= kMaxPairedMacs) {
        connectionLost();
        return;
      }
      index = static_cast<int>(pairedCount_++);
    }
    paired_[index].id = targetId_;
    paired_[index].name = incomingDocument_["mac_name"] | targetName_;
    paired_[index].token = token;
    store_.savePairedMacs(paired_, pairedCount_);
    connectedName_ = paired_[index].name;
    state_ = LinkState::Connected;
    setAudioReady(true);
    reconnectDelayMs_ = kReconnectMinMs;
    requestAgentList();
    if (settings_) {
      settings_->lastMacId = targetId_;
      persistSettings();
    }
    return;
  }
  if (type == "hello_ok") {
    parseBridgeMetadata(incomingDocument_);
    connectedName_ = incomingDocument_["mac_name"] | targetName_;
    state_ = LinkState::Connected;
    setAudioReady(true);
    reconnectDelayMs_ = kReconnectMinMs;
    requestAgentList();
    if (settings_) {
      settings_->lastMacId = targetId_;
      persistSettings();
    }
    return;
  }
  if (type == "auth_error") {
    const int index = pairedIndexById(targetId_);
    if (index >= 0) {
      paired_[index].token.clear();
      store_.savePairedMacs(paired_, pairedCount_);
    }
    targetToken_.clear();
    state_ = LinkState::AwaitingPairCode;
    sendHello();
    return;
  }
  if (type == "agent_status" || type == "agent_list") {
    parseAgentSnapshot(incomingDocument_);
    return;
  }
  // Every future/unknown type is deliberately ignored.
}

void PairingManager::parseBridgeMetadata(JsonDocument& document) {
  JsonVariantConst app = document["app"];
  bridgeVersion_ = app["version"] | "";
  bridgeBuild_ = app["build"] | 0U;
  JsonVariantConst protocol = document["protocol"];
  if (protocol.isNull()) {
    // A bridge without explicit protocol metadata is the shipped legacy v1.
    bridgeProtocolMajor_ = 1;
    bridgeProtocolMinor_ = 0;
  } else {
    bridgeProtocolMajor_ = protocol["major"] | 0;
    bridgeProtocolMinor_ = protocol["minor"] | 0;
  }
}

namespace {

AgentStatus parseAgentStatus(const char* value) {
  if (!value) return AgentStatus::Idle;
  if (!strcmp(value, "running")) return AgentStatus::Running;
  if (!strcmp(value, "needs_input")) return AgentStatus::NeedsInput;
  if (!strcmp(value, "ready")) return AgentStatus::Ready;
  if (!strcmp(value, "blocked")) return AgentStatus::Blocked;
  if (!strcmp(value, "offline")) return AgentStatus::Offline;
  return AgentStatus::Idle;
}

AgentPhase parseAgentPhase(const char* value) {
  if (!value) return AgentPhase::None;
  if (!strcmp(value, "thinking")) return AgentPhase::Thinking;
  if (!strcmp(value, "tool")) return AgentPhase::Tool;
  return AgentPhase::None;
}

AgentQuotaMode parseAgentQuotaMode(const char* value) {
  if (!value) return AgentQuotaMode::Unknown;
  if (!strcmp(value, "subscription")) return AgentQuotaMode::Subscription;
  if (!strcmp(value, "api")) return AgentQuotaMode::Api;
  return AgentQuotaMode::Unknown;
}

int8_t quotaRemaining(JsonVariantConst window) {
  if (window.isNull() || !window["remaining"].is<int>()) return -1;
  return static_cast<int8_t>(constrain(window["remaining"].as<int>(), 0, 100));
}

}  // namespace

void PairingManager::parseAgentSnapshot(JsonDocument& document) {
  const uint32_t sequence = document["seq"] | 0U;
  if (agentOnline_ && sequence < agentSeq_) return;
  agentSeq_ = sequence;
  agentFocusId_ = document["focus_id"].as<String>();
  agentFocusSeq_ = document["focus_seq"] | 0U;
  JsonVariantConst quota = document["quota"];
  // ArduinoJson 6 treats `variant | nullptr` as a null default even when the
  // variant contains a string. Use the typed conversion so api/subscription
  // modes survive the wire format instead of always degrading to Unknown.
  const char* quotaMode = quota["mode"].as<const char*>();
  if (quotaMode) {
    agentQuota_.mode = parseAgentQuotaMode(quotaMode);
  } else {
    // Older bridges expose only a subscription-availability boolean. They
    // cannot distinguish API from a failed lookup, so false remains Unknown.
    const bool available = quota["available"].is<bool>()
                               ? quota["available"].as<bool>()
                               : (!quota["weekly"].isNull() ||
                                  !quota["five_hour"].isNull());
    agentQuota_.mode = available ? AgentQuotaMode::Subscription
                                 : AgentQuotaMode::Unknown;
  }
  const bool subscription = agentQuota_.mode == AgentQuotaMode::Subscription;
  agentQuota_.weeklyRemaining = subscription
                                    ? quotaRemaining(quota["weekly"])
                                    : -1;
  agentQuota_.fiveHourRemaining = subscription
                                      ? quotaRemaining(quota["five_hour"])
                                      : -1;

  agentCount_ = 0;
  for (JsonObjectConst item : document["items"].as<JsonArrayConst>()) {
    if (agentCount_ >= kMaxAgentSessions) break;
    AgentSession& agent = agents_[agentCount_++];
    agent.id = item["id"].as<String>();
    agent.title = item["title"] | "Codex session";
    agent.project = item["project"].as<String>();
    agent.activity = item["activity"] | "Session ready";
    agent.status = parseAgentStatus(item["status"]);
    agent.phase = parseAgentPhase(item["phase"]);
    // Older CardBridge services did not send a phase. Treat an unqualified
    // Running snapshot as thinking instead of falsely showing a live command.
    if (agent.status == AgentStatus::Running && agent.phase == AgentPhase::None) {
      agent.phase = AgentPhase::Thinking;
    }
    agent.unread = item["unread"] | false;
  }
  agentOnline_ = true;
}

void PairingManager::requestAgentList() {
  StaticJsonDocument<256> request;
  request["t"] = "agent_list_req";
  request["limit"] = kMaxAgentSessions;
  sendDocument(request);
}

void PairingManager::disconnect(bool manual) {
  cancelConnectionAttempt();
  incoming_.clear();
  connectedName_.clear();
  state_ = LinkState::Offline;
  agentOnline_ = false;
  setAudioReady(false);
  manualDisconnect_ = manual;
  missedPongs_ = 0;
  compatibilityReason_.clear();
  requiredFirmware_.clear();
  if (manual) {
    targetId_.clear();
    targetToken_.clear();
    if (settings_) {
      settings_->lastMacId.clear();
      persistSettings();
    }
  }
}

void PairingManager::connectionLost() {
  cancelConnectionAttempt();
  connectedName_.clear();
  state_ = LinkState::Offline;
  agentOnline_ = false;
  setAudioReady(false);
  scheduleReconnect();
}

void PairingManager::scheduleReconnect() {
  nextConnectMs_ = millis() + reconnectDelayMs_;
  reconnectDelayMs_ = min<uint32_t>(reconnectDelayMs_ * 2, kReconnectMaxMs);
  rediscoveryRequired_ = true;
}

bool PairingManager::deletePairing(size_t index) {
  if (index >= pairedCount_) return false;
  if (pairedCurrent(index)) disconnect(true);
  for (size_t i = index; i + 1 < pairedCount_; ++i) paired_[i] = paired_[i + 1];
  --pairedCount_;
  return store_.savePairedMacs(paired_, pairedCount_);
}

bool PairingManager::audioEndpoint(IPAddress& ip, uint8_t token[32]) const {
  bool ready;
  uint8_t address[4];
  portENTER_CRITICAL(&audioMux_);
  ready = audioReady_;
  memcpy(address, audioIp_, sizeof(address));
  memcpy(token, audioToken_, 32);
  portEXIT_CRITICAL(&audioMux_);
  if (!ready) return false;
  ip = IPAddress(address[0], address[1], address[2], address[3]);
  return true;
}

bool PairingManager::audioStatus(uint32_t& received, uint32_t& updatedMs,
                                 bool& outputReady) const {
  bool seen;
  portENTER_CRITICAL(&audioMux_);
  seen = audioStatusSeen_;
  received = audioReceived_;
  updatedMs = audioStatusMs_;
  outputReady = audioOutputReady_;
  portEXIT_CRITICAL(&audioMux_);
  return seen;
}

int PairingManager::pairedIndexById(const String& id) const {
  for (size_t i = 0; i < pairedCount_; ++i) {
    if (paired_[i].id == id) return static_cast<int>(i);
  }
  return -1;
}

int PairingManager::discoveredIndexById(const String& id) const {
  for (size_t i = 0; i < discoveredCount_; ++i) {
    if (discovered_[i].id == id) return static_cast<int>(i);
  }
  return -1;
}

bool PairingManager::pairedOnline(size_t index) const {
  return index < pairedCount_ && discoveredIndexById(paired_[index].id) >= 0;
}

bool PairingManager::pairedCurrent(size_t index) const {
  return index < pairedCount_ && connected() && paired_[index].id == targetId_;
}

String PairingManager::statusText() const {
  switch (state_) {
    case LinkState::Offline: return "Mac offline";
    case LinkState::Discovering: return "Finding Mac...";
    case LinkState::Connecting: return "Connecting...";
    case LinkState::AwaitingPairCode: return "Enter pair code";
    case LinkState::Authenticating: return "Authenticating...";
    case LinkState::Connected: return String("Connected ") + connectedName_;
    case LinkState::Incompatible: return "Update required";
  }
  return "Mac offline";
}

void PairingManager::persistSettings() {
  if (settings_) store_.saveSettings(*settings_);
}

void PairingManager::setAudioReady(bool ready) {
  uint8_t decoded[32]{};
  if (ready) {
    if (targetToken_.length() != 64) ready = false;
    for (size_t i = 0; ready && i < 32; ++i) {
      const char highChar = targetToken_[i * 2];
      const char lowChar = targetToken_[i * 2 + 1];
      const int high = isDigit(highChar) ? highChar - '0' :
                       (tolower(highChar) >= 'a' && tolower(highChar) <= 'f'
                            ? tolower(highChar) - 'a' + 10 : -1);
      const int low = isDigit(lowChar) ? lowChar - '0' :
                      (tolower(lowChar) >= 'a' && tolower(lowChar) <= 'f'
                           ? tolower(lowChar) - 'a' + 10 : -1);
      if (high < 0 || low < 0) {
        ready = false;
      } else {
        decoded[i] = static_cast<uint8_t>((high << 4) | low);
      }
    }
  }
  portENTER_CRITICAL(&audioMux_);
  audioReady_ = ready;
  audioStatusSeen_ = false;
  audioOutputReady_ = false;
  audioReceived_ = 0;
  audioStatusMs_ = 0;
  if (ready) {
    for (size_t i = 0; i < 4; ++i) audioIp_[i] = targetIp_[i];
    memcpy(audioToken_, decoded, sizeof(audioToken_));
  } else {
    memset(audioToken_, 0, sizeof(audioToken_));
  }
  portEXIT_CRITICAL(&audioMux_);
}

}  // namespace cardbridge
