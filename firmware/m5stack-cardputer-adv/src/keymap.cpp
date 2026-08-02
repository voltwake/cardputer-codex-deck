#include "keymap.h"

#include <M5Cardputer.h>

namespace cardbridge {

const char* mapFnKey(uint8_t key, uint8_t typelessFunctionKey) {
  switch (key) {
    case ' ': {  // Dedicated Typeless hold-to-record key: Fn+Space.
      static const char* functionKeys[] = {"f13", "f14", "f15", "f16"};
      const uint8_t index = typelessFunctionKey >= 13 && typelessFunctionKey <= 16
                                ? typelessFunctionKey - 13 : 0;
      return functionKeys[index];
    }
    // Follow the arrow legends printed on the Cardputer keyboard.
    case ';': return "up";
    case ',': return "left";
    case '.': return "down";
    case '/': return "right";
    case '`': return "escape";
    case '[': return "home";
    case ']': return "end";
    case KEY_BACKSPACE: return "delete_forward";
    default: return nullptr;
  }
}

const char* mapSpecialKey(uint8_t key) {
  switch (key) {
    case KEY_BACKSPACE: return "backspace";
    case KEY_TAB: return "tab";
    case KEY_ENTER: return "enter";
    default: return nullptr;
  }
}

bool isKeyboardModifier(uint8_t key) {
  return key == KEY_LEFT_CTRL || key == KEY_LEFT_SHIFT || key == KEY_LEFT_ALT ||
         key == KEY_OPT;
}

const char* mapModifier(uint8_t key) {
  switch (key) {
    case KEY_LEFT_CTRL: return "ctrl";
    case KEY_LEFT_ALT: return "cmd";
    case KEY_OPT: return "alt";
    default: return nullptr;
  }
}

}  // namespace cardbridge
