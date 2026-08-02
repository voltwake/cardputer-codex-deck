#pragma once

#include <M5Cardputer.h>

#include "models.h"
#include "pairing.h"

namespace cardbridge {

class KeyTransmitter {
 public:
  KeyTransmitter(PairingManager& pairing, const DeviceSettings& settings)
      : pairing_(pairing), settings_(settings) {}

  void tick(bool uiConsumesKeyboard);
  void releaseAll();
  uint32_t sentKeys() const { return sentKeys_; }

 private:
  struct ActiveKey {
    char key[20]{};
    uint8_t physical = 0xFF;
    bool cmd = false;
    bool shift = false;
    bool option = false;
    bool control = false;
  };

  size_t buildCurrent(ActiveKey* output, size_t capacity);
  bool contains(const ActiveKey* list, size_t count, const char* key) const;
  const ActiveKey* previousPhysical(uint8_t physical) const;
  void send(const ActiveKey& key, const char* action);

  PairingManager& pairing_;
  const DeviceSettings& settings_;
  ActiveKey previous_[6];
  size_t previousCount_ = 0;
  uint32_t sentKeys_ = 0;
};

}  // namespace cardbridge
