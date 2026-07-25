#pragma once

#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <WiFiClient.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "app_config.h"
#include "models.h"
#include "settings_store.h"
#include "wifi_mgr.h"

namespace cardbridge {

class PairingManager {
 public:
  PairingManager(SettingsStore& store, WifiManager& wifi)
      : store_(store), wifi_(wifi) {}

  void begin(DeviceSettings* settings);
  void tick();
  void requestDiscovery();
  bool connectToDiscovered(size_t index);
  bool connectToPaired(size_t index);
  void disconnect(bool manual = true);
  bool deletePairing(size_t index);
  bool submitPairCode(const String& sixDigits);

  bool sendKey(const char* key, const char* action, bool cmd, bool shift,
               bool option, bool control);
  bool sendAgentAck(const String& sessionId);
  bool audioEndpoint(IPAddress& ip, uint8_t token[32]) const;
  bool audioStatus(uint32_t& received, uint32_t& updatedMs,
                   bool& outputReady) const;

  LinkState state() const { return state_; }
  bool connected() const { return state_ == LinkState::Connected; }
  String connectedName() const { return connectedName_; }
  String statusText() const;
  bool pairCodeRequested() const { return state_ == LinkState::AwaitingPairCode; }
  const String& bridgeVersion() const { return bridgeVersion_; }
  uint32_t bridgeBuild() const { return bridgeBuild_; }
  uint8_t bridgeProtocolMajor() const { return bridgeProtocolMajor_; }
  uint8_t bridgeProtocolMinor() const { return bridgeProtocolMinor_; }
  const String& compatibilityReason() const { return compatibilityReason_; }
  const String& requiredFirmware() const { return requiredFirmware_; }

  size_t pairedCount() const { return pairedCount_; }
  const PairedMac& paired(size_t index) const { return paired_[index]; }
  bool pairedOnline(size_t index) const;
  bool pairedCurrent(size_t index) const;

  size_t discoveredCount() const { return discoveredCount_; }
  const DiscoveredMac& discovered(size_t index) const { return discovered_[index]; }

  bool agentOnline() const { return agentOnline_ && connected(); }
  size_t agentCount() const { return agentCount_; }
  const AgentSession& agent(size_t index) const { return agents_[index]; }
  const String& agentFocusId() const { return agentFocusId_; }
  uint32_t agentFocusSeq() const { return agentFocusSeq_; }
  const AgentQuota& agentQuota() const { return agentQuota_; }

 private:
  struct ConnectResult {
    uint32_t generation;
    bool connected;
  };

  struct ConnectTaskContext {
    PairingManager* manager;
    IPAddress ip;
    uint16_t port;
    uint32_t generation;
  };

  static void connectTaskEntry(void* argument);
  int pairedIndexById(const String& id) const;
  int discoveredIndexById(const String& id) const;
  bool startDiscovery(bool forReconnect);
  void pollDiscovery();
  void collectDiscoveryResults(mdns_result_t* results);
  void attemptConnection();
  void pollConnectionAttempt();
  void cancelConnectionAttempt();
  void sendHello();
  bool sendDocument(JsonDocument& document);
  void readIncoming();
  void handleLine(const String& line);
  void parseBridgeMetadata(JsonDocument& document);
  void parseAgentSnapshot(JsonDocument& document);
  void requestAgentList();
  void connectionLost();
  void scheduleReconnect();
  void persistSettings();
  void setAudioReady(bool ready);

  SettingsStore& store_;
  WifiManager& wifi_;
  DeviceSettings* settings_ = nullptr;
  PairedMac paired_[kMaxPairedMacs];
  DiscoveredMac discovered_[kMaxDiscoveredMacs];
  size_t pairedCount_ = 0;
  size_t discoveredCount_ = 0;

  WiFiClient client_;
  String deviceId_;
  String incoming_;
  String targetId_;
  String targetName_;
  String targetToken_;
  IPAddress targetIp_;
  uint16_t targetPort_ = kControlPort;
  String connectedName_;
  String bridgeVersion_;
  uint32_t bridgeBuild_ = 0;
  uint8_t bridgeProtocolMajor_ = 0;
  uint8_t bridgeProtocolMinor_ = 0;
  String compatibilityReason_;
  String requiredFirmware_;

  AgentSession agents_[kMaxAgentSessions];
  size_t agentCount_ = 0;
  String agentFocusId_;
  uint32_t agentFocusSeq_ = 0;
  AgentQuota agentQuota_;
  uint32_t agentSeq_ = 0;
  bool agentOnline_ = false;
  // The largest inbound message is an eight-session agent snapshot. Keeping
  // its JSON arena in the object avoids a 4 KiB loop-task stack spike and
  // repeated heap fragmentation on every status update.
  StaticJsonDocument<8192> incomingDocument_;

  LinkState state_ = LinkState::Offline;
  bool mdnsStarted_ = false;
  mdns_search_once_t* discoverySearch_ = nullptr;
  bool discoveryRequested_ = false;
  bool discoveryForReconnect_ = false;
  bool rediscoveryRequired_ = true;
  bool manualDisconnect_ = false;
  QueueHandle_t connectResultQueue_ = nullptr;
  bool connectInFlight_ = false;
  bool cancelConnect_ = false;
  uint32_t connectGeneration_ = 0;
  uint8_t missedPongs_ = 0;
  uint32_t lastHeartbeatMs_ = 0;
  uint32_t nextConnectMs_ = 0;
  uint32_t reconnectDelayMs_ = kReconnectMinMs;

  // Only POD data crosses from the UI/control loop to the two audio tasks.
  // This avoids cross-core access to Arduino String internals.
  mutable portMUX_TYPE audioMux_ = portMUX_INITIALIZER_UNLOCKED;
  bool audioReady_ = false;
  uint8_t audioIp_[4]{};
  uint8_t audioToken_[32]{};
  bool audioStatusSeen_ = false;
  bool audioOutputReady_ = false;
  uint32_t audioReceived_ = 0;
  uint32_t audioStatusMs_ = 0;
};

}  // namespace cardbridge
