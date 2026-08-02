#!/usr/bin/env python3
"""Pack a Codex pet atlas into tiny flash-only Cardputer animation data.

The official app atlas (1536x1872, 8x9 cells) and extended v2 atlas
(1536x2288, 8x11 cells) share the same first nine animation rows. This adapter
selects the five semantic rows used by CardBridge, scales each frame to 72x72,
quantizes the whole set to one 15-colour palette, and emits row-safe RLE for
direct drawing from ESP32 flash. ``--demo`` remains a deterministic fallback.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw


APP_ATLAS_SIZE = (1536, 1872)
V2_ATLAS_SIZE = (1536, 2288)
ATLAS_SIZES = (APP_ATLAS_SIZE, V2_ATLAS_SIZE)
CELL_SIZE = (192, 208)
FRAME_SIZE = (72, 72)
MAX_PACKED_BYTES = 128 * 1024


@dataclass(frozen=True)
class AnimationSpec:
    key: str
    enum_name: str
    row: int
    durations: tuple[int, ...]


SPECS = (
    AnimationSpec("idle", "Idle", 0, (280, 110, 110, 140, 140, 320)),
    AnimationSpec("failed", "Failed", 5, (140, 140, 140, 140, 140, 140, 140, 240)),
    AnimationSpec("waiting", "Waiting", 6, (150, 150, 150, 150, 150, 260)),
    AnimationSpec("running", "Running", 7, (120, 120, 120, 120, 120, 220)),
    AnimationSpec("review", "Review", 8, (150, 150, 150, 150, 150, 280)),
)


def image_pixels(image: Image.Image):
    """Pillow 12/13 compatibility without triggering getdata deprecations."""
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


def load_atlas(args: argparse.Namespace) -> Image.Image | None:
    if args.demo:
        return None
    atlas_path = args.atlas
    if args.pet_dir:
        manifest_path = args.pet_dir / "pet.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest.get("spriteVersionNumber")
        if version not in (None, 1, 2):
            raise SystemExit(f"{manifest_path}: unsupported spriteVersionNumber {version}")
        atlas_path = args.pet_dir / manifest.get("spritesheetPath", "spritesheet.webp")
    if atlas_path is None:
        raise SystemExit("provide --pet-dir, --atlas, or --demo")
    image = Image.open(atlas_path).convert("RGBA")
    if image.size not in ATLAS_SIZES:
        expected = " or ".join(f"{width}x{height}" for width, height in ATLAS_SIZES)
        raise SystemExit(f"{atlas_path}: expected {expected}, got {image.size}")
    return image


def atlas_frames(atlas: Image.Image, spec: AnimationSpec) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for column in range(len(spec.durations)):
        x = column * CELL_SIZE[0]
        y = spec.row * CELL_SIZE[1]
        source = atlas.crop((x, y, x + CELL_SIZE[0], y + CELL_SIZE[1]))
        source.thumbnail(FRAME_SIZE, Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", FRAME_SIZE)
        frame.alpha_composite(
            source,
            ((FRAME_SIZE[0] - source.width) // 2, (FRAME_SIZE[1] - source.height) // 2),
        )
        frames.append(frame)
    return frames


def demo_frame(state: str, index: int, count: int) -> Image.Image:
    """Procedural bring-up mascot, intentionally replaceable by a v2 pet."""
    scale = 3
    image = Image.new("RGBA", (FRAME_SIZE[0] * scale, FRAME_SIZE[1] * scale))
    draw = ImageDraw.Draw(image)
    phase = index / count * math.tau
    bob = round(math.sin(phase) * 2) * scale
    if state == "running":
        bob = (-2 if index % 2 else 2) * scale
    if state == "failed":
        bob = (-2 if index % 2 else 2) * scale

    def box(coords: tuple[int, int, int, int], fill: str, radius: int = 0) -> None:
        scaled = tuple(value * scale for value in coords)
        if radius:
            draw.rounded_rectangle(scaled, radius=radius * scale, fill=fill)
        else:
            draw.rectangle(scaled, fill=fill)

    # Ground shadow and two little feet.
    draw.ellipse((18 * scale, 62 * scale, 54 * scale, 67 * scale), fill="#16233a")
    foot = 2 if state == "running" and index % 2 else 0
    box((23 - foot, 55, 32 - foot, 64), "#3044cc", 3)
    box((40 + foot, 55, 49 + foot, 64), "#3044cc", 3)

    # Terminal-cloud body, with a readable >_ face at 72px.
    body = (12, 12 + bob // scale, 60, 58 + bob // scale)
    box(body, "#3e49ff", 15)
    box((16, 16 + bob // scale, 56, 53 + bob // scale), "#6f8dff", 12)
    eye_y = 32 + bob // scale
    if state == "idle" and index in (2, 3):
        box((24, eye_y + 2, 30, eye_y + 3), "#f4f7ff", 1)
    else:
        draw.line(
            ((24 * scale, (eye_y - 3) * scale), (29 * scale, eye_y * scale),
             (24 * scale, (eye_y + 3) * scale)),
            fill="#f4f7ff", width=2 * scale, joint="curve",
        )
    box((37, eye_y + 2, 47, eye_y + 4), "#f4f7ff", 1)

    if state == "running":
        for particle in range(2):
            x = 5 + ((index * 7 + particle * 11) % 11)
            box((x, 42 + particle * 7, x + 5, 44 + particle * 7), "#22d3ee", 1)
    elif state == "waiting":
        for dot in range(3):
            color = "#f8cc5c" if dot == index % 3 else "#52627c"
            draw.ellipse(((27 + dot * 8) * scale, 7 * scale,
                          (31 + dot * 8) * scale, 11 * scale), fill=color)
    elif state == "review":
        hand_y = 17 + (index % 2) * 5
        draw.line(((58 * scale, 34 * scale), (66 * scale, hand_y * scale)),
                  fill="#f8cc5c", width=4 * scale)
        draw.ellipse((63 * scale, (hand_y - 3) * scale, 69 * scale,
                      (hand_y + 3) * scale), fill="#f8cc5c")
    elif state == "failed":
        box((58, 6, 69, 24), "#ff506c", 5)
        box((63, 9, 65, 17), "#ffffff", 1)
        box((63, 19, 65, 21), "#ffffff", 1)

    return image.resize(FRAME_SIZE, Image.Resampling.LANCZOS)


def build_frames(atlas: Image.Image | None) -> dict[str, list[Image.Image]]:
    return {
        spec.key: (
            atlas_frames(atlas, spec)
            if atlas is not None
            else [demo_frame(spec.key, i, len(spec.durations))
                  for i in range(len(spec.durations))]
        )
        for spec in SPECS
    }


def make_palette(frames: Iterable[Image.Image]) -> list[tuple[int, int, int]]:
    samples: list[tuple[int, int, int]] = []
    for frame in frames:
        samples.extend((r, g, b) for r, g, b, a in image_pixels(frame) if a >= 64)
    if not samples:
        return [(0, 0, 0)] * 16
    sample = Image.new("RGB", (len(samples), 1))
    sample.putdata(samples)
    quantized = sample.quantize(colors=15, method=Image.Quantize.MEDIANCUT)
    raw = quantized.getpalette() or []
    used = sorted(set(image_pixels(quantized)))
    palette = [(0, 0, 0)]
    palette.extend(tuple(raw[i * 3:i * 3 + 3]) for i in used)
    return (palette + [(0, 0, 0)] * 16)[:16]


def index_frame(frame: Image.Image, palette: list[tuple[int, int, int]]) -> list[int]:
    colors = palette[1:]
    result: list[int] = []
    for red, green, blue, alpha in image_pixels(frame):
        if alpha < 64:
            result.append(0)
            continue
        best = min(
            range(len(colors)),
            key=lambda i: ((red - colors[i][0]) ** 2 +
                           (green - colors[i][1]) ** 2 +
                           (blue - colors[i][2]) ** 2),
        )
        result.append(best + 1)
    return result


def row_rle(indices: list[int]) -> bytes:
    encoded = bytearray()
    width, height = FRAME_SIZE
    for y in range(height):
        row = indices[y * width:(y + 1) * width]
        start = 0
        while start < width:
            value = row[start]
            end = start + 1
            while end < width and row[end] == value and end - start < 255:
                end += 1
            encoded.extend((end - start, value))
            start = end
    return bytes(encoded)


def rgb565(color: tuple[int, int, int]) -> int:
    r, g, b = color
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def byte_lines(data: bytes) -> str:
    chunks = []
    for start in range(0, len(data), 20):
        chunks.append("    " + ", ".join(f"0x{value:02x}" for value in data[start:start + 20]))
    return ",\n".join(chunks)


def emit(frames: dict[str, list[Image.Image]], output_dir: Path) -> int:
    palette = make_palette(frame for values in frames.values() for frame in values)
    encoded: dict[str, list[bytes]] = {
        key: [row_rle(index_frame(frame, palette)) for frame in values]
        for key, values in frames.items()
    }
    packed_size = sum(len(frame) for animation in encoded.values() for frame in animation)
    if packed_size > MAX_PACKED_BYTES:
        raise SystemExit(
            f"packed pet is {packed_size} bytes; firmware limit is {MAX_PACKED_BYTES}"
        )

    animation_ids = ", ".join(spec.enum_name for spec in SPECS)
    header = f"""// Generated by tools/pack_pet.py; do not hand-edit.\n#pragma once\n\n#include <Arduino.h>\n\nnamespace cardbridge::pet_assets {{\n\nconstexpr uint8_t kFrameWidth = 72;\nconstexpr uint8_t kFrameHeight = 72;\n\nenum class AnimationId : uint8_t {{ {animation_ids} }};\n\nstruct Frame {{\n  const uint8_t* data;\n  uint16_t length;\n  uint16_t durationMs;\n}};\n\nstruct Animation {{\n  const Frame* frames;\n  uint8_t count;\n}};\n\nextern const uint16_t kPalette[16];\nconst Animation& get(AnimationId id);\n\n}}  // namespace cardbridge::pet_assets\n"""
    body = [
        "// Generated by tools/pack_pet.py; do not hand-edit.",
        '#include "pet_assets.h"',
        "",
        "namespace cardbridge::pet_assets {",
        "",
        "const uint16_t kPalette[16] PROGMEM = {",
        "    " + ", ".join(f"0x{rgb565(color):04x}" for color in palette),
        "};",
        "",
    ]
    for spec in SPECS:
        for index, data in enumerate(encoded[spec.key]):
            body.extend([
                f"const uint8_t k{spec.enum_name}{index}[] PROGMEM = {{",
                byte_lines(data),
                "};",
            ])
        body.append(f"const Frame k{spec.enum_name}Frames[] PROGMEM = {{")
        for index, (data, duration) in enumerate(zip(encoded[spec.key], spec.durations)):
            body.append(
                f"    {{k{spec.enum_name}{index}, {len(data)}, {duration}}},"
            )
        body.extend(["};", ""])
    body.extend([
        "const Animation kAnimations[] = {",
        *[
            f"    {{k{spec.enum_name}Frames, "
            f"static_cast<uint8_t>(sizeof(k{spec.enum_name}Frames) / sizeof(Frame))}},"
            for spec in SPECS
        ],
        "};",
        "",
        "const Animation& get(AnimationId id) {",
        "  return kAnimations[static_cast<uint8_t>(id)];",
        "}",
        "",
        "}  // namespace cardbridge::pet_assets",
        "",
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pet_assets.h").write_text(header, encoding="utf-8")
    (output_dir / "pet_assets.cpp").write_text("\n".join(body), encoding="utf-8")
    return packed_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pet-dir", type=Path)
    source.add_argument("--atlas", type=Path)
    source.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("firmware/m5stack-cardputer-adv/src"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    atlas = load_atlas(args)
    frames = build_frames(atlas)
    byte_count = emit(frames, args.output_dir)
    raw = sum(len(values) for values in frames.values()) * FRAME_SIZE[0] * FRAME_SIZE[1]
    print(f"packed {sum(map(len, frames.values()))} frames: {raw} indexed bytes -> "
          f"{byte_count} RLE bytes ({byte_count / raw:.1%})")


if __name__ == "__main__":
    main()
