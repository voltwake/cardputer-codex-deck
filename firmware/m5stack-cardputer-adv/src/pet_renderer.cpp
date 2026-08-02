#include "pet_renderer.h"

namespace cardbridge {

pet_assets::AnimationId PetRenderer::animationFor(PetVisualState state) const {
  switch (state) {
    case PetVisualState::Running: return pet_assets::AnimationId::Running;
    case PetVisualState::Thinking:
    case PetVisualState::NeedsInput: return pet_assets::AnimationId::Waiting;
    case PetVisualState::Ready: return pet_assets::AnimationId::Review;
    case PetVisualState::Offline:
    case PetVisualState::Blocked: return pet_assets::AnimationId::Failed;
    case PetVisualState::Idle: return pet_assets::AnimationId::Idle;
  }
  return pet_assets::AnimationId::Idle;
}

void PetRenderer::draw(M5Canvas& canvas, PetVisualState state, int x, int y,
                       uint32_t nowMs, uint16_t size) {
  if (state != state_) {
    state_ = state;
    frameIndex_ = 0;
    frameStartedMs_ = nowMs;
  }
  const pet_assets::Animation& animation = pet_assets::get(animationFor(state));
  const pet_assets::Frame& current = animation.frames[frameIndex_];
  if (nowMs - frameStartedMs_ >= current.durationMs) {
    frameIndex_ = (frameIndex_ + 1) % animation.count;
    frameStartedMs_ = nowMs;
  }
  drawFrame(canvas, animation.frames[frameIndex_], x, y, size);
  if (state == PetVisualState::Offline) {
    canvas.drawLine(x + 11 * size / pet_assets::kFrameWidth,
                    y + 61 * size / pet_assets::kFrameHeight,
                    x + 61 * size / pet_assets::kFrameWidth,
                    y + 11 * size / pet_assets::kFrameHeight, 0x8410);
  }
}

void PetRenderer::drawFrame(M5Canvas& canvas, const pet_assets::Frame& frame,
                            int x, int y, uint16_t size) const {
  uint16_t cursor = 0;
  uint16_t pixel = 0;
  while (cursor + 1 < frame.length &&
         pixel < pet_assets::kFrameWidth * pet_assets::kFrameHeight) {
    const uint8_t count = frame.data[cursor++];
    const uint8_t paletteIndex = frame.data[cursor++];
    const int row = pixel / pet_assets::kFrameWidth;
    const int column = pixel % pet_assets::kFrameWidth;
    // The packer deliberately terminates every run at a row boundary.
    if (paletteIndex != 0) {
      if (size == pet_assets::kFrameWidth) {
        canvas.drawFastHLine(x + column, y + row, count,
                             pet_assets::kPalette[paletteIndex]);
      } else {
        const int left = column * size / pet_assets::kFrameWidth;
        const int right = (column + count) * size / pet_assets::kFrameWidth;
        const int top = row * size / pet_assets::kFrameHeight;
        const int bottom = (row + 1) * size / pet_assets::kFrameHeight;
        canvas.fillRect(x + left, y + top, max(1, right - left),
                        max(1, bottom - top),
                        pet_assets::kPalette[paletteIndex]);
      }
    }
    pixel += count;
  }
}

}  // namespace cardbridge
