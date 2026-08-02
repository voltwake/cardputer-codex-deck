// Generated font interface. Rebuild data with tools/build_ui_font.py.
#pragma once

#include <Arduino.h>

namespace cardbridge::ui_font_data {

constexpr uint16_t kGlyphCount = 7543;
constexpr uint8_t kPixelSize = 13;
extern const uint8_t kData[]
    asm("_binary_assets_fonts_cardbridge_ui_13_bff_start");
extern const uint8_t kDataEnd[]
    asm("_binary_assets_fonts_cardbridge_ui_13_bff_end");

inline size_t size() {
  return static_cast<size_t>(kDataEnd - kData);
}

}  // namespace cardbridge::ui_font_data
