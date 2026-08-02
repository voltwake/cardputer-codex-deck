#pragma once

#include <Arduino.h>

namespace cardbridge {

// This file is the single place for Cardputer -> macOS mappings. Typeless is
// configured for F13 by default; change this table if a different dedicated
// key or fn layout is desired.
const char* mapFnKey(uint8_t physicalKey, uint8_t typelessFunctionKey = 13);
const char* mapSpecialKey(uint8_t physicalKey);
bool isKeyboardModifier(uint8_t physicalKey);
const char* mapModifier(uint8_t physicalKey);

}  // namespace cardbridge
