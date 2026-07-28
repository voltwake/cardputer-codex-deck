#!/usr/bin/env python3
"""Render deterministic Cardputer UI previews for the public documentation.

The previews use the shipped background and pet RLE data, plus the geometry,
colours, labels, and example states from ``src/ui.cpp``. They intentionally use
safe sample task text instead of reading a live Codex session.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images"
WIDTH = 240
HEIGHT = 135
SCALE = 4
NOW_MS = 2_400


def rgb565(value: int) -> tuple[int, int, int]:
    return (
        ((value >> 11) & 0x1F) * 255 // 31,
        ((value >> 5) & 0x3F) * 255 // 63,
        (value & 0x1F) * 255 // 31,
    )


BACKGROUND = rgb565(0x0841)
PANEL = rgb565(0x18E3)
PANEL_DEEP = rgb565(0x08A2)
PANEL_SELECTED = rgb565(0x0339)
LINE = rgb565(0x2A2C)
ACCENT = rgb565(0x05FF)
ACCENT_WARM = rgb565(0xFD20)
TEXT_DIM = rgb565(0x8410)
GOOD = rgb565(0x07E9)
BAD = rgb565(0xF9E7)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


FONT_MICRO = font(7)
FONT_SMALL = font(8)
FONT_BODY = font(10)
FONT_TITLE = font(11)


def rect(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int,
         *, fill=None, outline=None, radius: int = 0) -> None:
    box = (x, y, x + width - 1, y + height - 1)
    if radius:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline)
    else:
        draw.rectangle(box, fill=fill, outline=outline)


def blend(start: tuple[int, int, int], end: tuple[int, int, int],
          amount: int) -> tuple[int, int, int]:
    return tuple(
        (left * (255 - amount) + right * amount) // 255
        for left, right in zip(start, end)
    )


def centered_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                  *, fill=WHITE, face=FONT_SMALL) -> None:
    draw.text(xy, text, font=face, fill=fill, anchor="mm")


def load_pet_frame(name: str) -> Image.Image:
    source = (ROOT / "src" / "pet_assets.cpp").read_text(encoding="utf-8")
    palette_match = re.search(
        r"const uint16_t kPalette\[16\] PROGMEM = \{(.*?)\};", source, re.S
    )
    frame_match = re.search(
        rf"const uint8_t {re.escape(name)}\[\] PROGMEM = \{{(.*?)\}};",
        source,
        re.S,
    )
    if not palette_match or not frame_match:
        raise RuntimeError(f"could not parse {name} from src/pet_assets.cpp")
    palette = [rgb565(int(value, 16)) for value in re.findall(r"0x[0-9a-fA-F]+", palette_match.group(1))]
    encoded = [int(value, 16) for value in re.findall(r"0x[0-9a-fA-F]+", frame_match.group(1))]
    pixels: list[tuple[int, int, int, int]] = []
    for index in range(0, len(encoded), 2):
        count, palette_index = encoded[index:index + 2]
        color = (*palette[palette_index], 0 if palette_index == 0 else 255)
        pixels.extend([color] * count)
    if len(pixels) != 72 * 72:
        raise RuntimeError(f"{name} decoded to {len(pixels)} pixels")
    image = Image.new("RGBA", (72, 72))
    image.putdata(pixels)
    return image


def paste_pet(image: Image.Image, frame_name: str, x: int, y: int,
              size: int) -> None:
    pet = load_pet_frame(frame_name).resize((size, size), Image.Resampling.NEAREST)
    image.alpha_composite(pet, (x, y))


def draw_keyboard(draw: ImageDraw.ImageDraw, x: int, y: int,
                  enabled: bool = True) -> None:
    color = ACCENT if enabled else TEXT_DIM
    rect(draw, x, y, 18, 12, fill=color if enabled else None, outline=color,
         radius=2)
    key_color = BLACK if enabled else color
    for column in range(4):
        rect(draw, x + 3 + column * 3, y + 3, 2, 2, fill=key_color)
    rect(draw, x + 3, y + 7, 12, 2, fill=key_color)
    if not enabled:
        draw.line((x + 2, y + 11, x + 16, y + 1), fill=BAD)


def draw_wifi(draw: ImageDraw.ImageDraw, x: int, y: int, bars: int,
              active=GOOD, inactive=LINE) -> None:
    for index in range(4):
        height = 3 + index * 3
        rect(draw, x + index * 4, y + 12 - height, 3, height,
             fill=active if index < bars else inactive)


def draw_battery(draw: ImageDraw.ImageDraw, x: int, y: int, level: int,
                 *, charging: bool = False, compact: bool = False) -> None:
    body_width = 13 if compact else 17
    body_height = 8 if compact else 10
    outline = ACCENT_WARM if charging else TEXT_DIM
    fill = ACCENT_WARM if charging else GOOD if level > 30 else BAD
    rect(draw, x, y, body_width, body_height, outline=outline)
    rect(draw, x + body_width, y + (body_height - 4) // 2, 2, 4,
         fill=outline)
    if level > 0:
        inner = body_width - 4
        rect(draw, x + 2, y + 2, max(1, inner * level // 100),
             body_height - 4, fill=fill)
    if charging:
        center_x = x + body_width // 2
        middle_y = y + body_height // 2
        draw.line((center_x + 1, y + 1, center_x - 2, middle_y,
                   center_x + 1, middle_y, center_x - 1,
                   y + body_height - 2), fill=BLACK)
    text_color = ACCENT_WARM if charging else BAD if level <= 15 else WHITE
    draw.text((x + body_width + 5, y + body_height // 2), f"{level}%",
              font=FONT_MICRO, fill=text_color, anchor="lm")


def draw_status_bar(draw: ImageDraw.ImageDraw) -> None:
    rect(draw, 0, 0, WIDTH, 20, fill=BLACK)
    draw_keyboard(draw, 4, 4, True)
    draw_wifi(draw, 28, 4, 4, active=GOOD, inactive=PANEL)
    centered_text(draw, (112, 10), "CODEX DECK", face=FONT_SMALL)
    draw_battery(draw, 184, 5, 76, charging=True)


def draw_angular_panel(draw: ImageDraw.ImageDraw, x: int, y: int, width: int,
                       height: int, selected: bool = False) -> None:
    background = PANEL_SELECTED if selected else PANEL
    rect(draw, x + 2, y, width - 4, height, fill=background)
    rect(draw, x, y + 2, width, height - 4, fill=background)
    rect(draw, x + 2, y + 2, width - 4, height - 4, outline=LINE)
    edge = ACCENT if selected else LINE
    draw.line((x, y + 2, x + 6, y + 2), fill=edge)
    draw.line((x, y + 2, x, y + 8), fill=edge)
    draw.line((x + width - 7, y + 2, x + width - 1, y + 2), fill=edge)
    draw.line((x + width - 1, y + 2, x + width - 1, y + 8), fill=edge)
    draw.line((x, y + height - 3, x + 6, y + height - 3), fill=edge)
    draw.line((x, y + height - 8, x, y + height - 2), fill=edge)
    draw.line((x + width - 7, y + height - 3, x + width - 1,
               y + height - 3), fill=edge)
    draw.line((x + width - 1, y + height - 8, x + width - 1,
               y + height - 2), fill=edge)


def draw_workshop_stage(draw: ImageDraw.ImageDraw, x: int, y: int,
                        width: int, height: int) -> None:
    rect(draw, x, y, width, height, fill=PANEL_DEEP, outline=LINE)
    rect(draw, x + 3, y + 3, width - 6, height * 42 // 100, fill=BACKGROUND)
    horizon = y + height * 46 // 100
    rect(draw, x + 3, horizon, width - 6, y + height - horizon - 3, fill=PANEL)
    draw.line((x + 3, horizon + 8, x + width - 4, horizon + 8), fill=LINE)
    draw.line((x + 3, horizon + 23, x + width - 4, horizon + 23), fill=LINE)
    draw.line((x + width // 2, horizon + 2, x + width // 2 - 14,
               y + height - 3), fill=LINE)
    draw.line((x + width // 2, horizon + 2, x + width // 2 + 14,
               y + height - 3), fill=LINE)
    rect(draw, x + 5, horizon + 2, 15, 3, fill=LINE)
    rect(draw, x + width - 20, horizon + 2, 15, 3, fill=LINE)
    draw.line((x + 42, y + 4, x + 42, y + height * 36 // 100), fill=ACCENT)


def draw_home() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), (*BACKGROUND, 255))
    draw = ImageDraw.Draw(image)
    for x in range(15, WIDTH, 46):
        draw.line((x, 19, x, HEIGHT - 1), fill=LINE)
    draw.line((0, 76, WIDTH - 1, 76), fill=LINE)
    draw.line((4, 132, 55, 132), fill=LINE)
    draw.line((183, 132, 232, 132), fill=LINE)
    draw_status_bar(draw)

    draw_angular_panel(draw, 4, 24, 108, 105, selected=True)
    draw_workshop_stage(draw, 9, 29, 98, 63)
    paste_pet(image, "kRunning2", 22, 25, 72)
    rect(draw, 9, 95, 98, 30, fill=PANEL_DEEP)
    draw.line((9, 95, 106, 95), fill=LINE)
    rect(draw, 13, 99, 3, 3, fill=ACCENT)
    draw.text((20, 97), "CODEX", font=FONT_SMALL, fill=WHITE)
    draw.text((103, 97), "RUNNING", font=FONT_MICRO, fill=ACCENT, anchor="ra")
    rect(draw, 13, 116, 89, 3, fill=BACKGROUND)
    rect(draw, 43, 116, 24, 3, fill=ACCENT)

    draw_angular_panel(draw, 118, 24, 58, 50)
    draw_angular_panel(draw, 179, 24, 57, 50)
    draw_angular_panel(draw, 118, 79, 58, 50)
    draw_angular_panel(draw, 179, 79, 57, 50)
    draw_wifi(draw, 139, 33, 4, active=GOOD, inactive=LINE)
    rect(draw, 199, 34, 16, 12, outline=GOOD)
    draw.line((202, 49, 211, 49), fill=GOOD)
    draw.line((207, 46, 207, 49), fill=GOOD)
    rect(draw, 141, 89, 12, 12, fill=ACCENT_WARM)
    draw.line((147, 84, 147, 87), fill=ACCENT_WARM, width=2)
    draw.line((147, 102, 147, 105), fill=ACCENT_WARM, width=2)
    draw.line((136, 95, 139, 95), fill=ACCENT_WARM, width=2)
    draw.line((154, 95, 157, 95), fill=ACCENT_WARM, width=2)
    draw.ellipse((197, 85, 217, 105), fill=rgb565(0x793B))
    draw.ellipse((203, 82, 221, 100), fill=PANEL)
    centered_text(draw, (147, 64), "WIFI", face=FONT_SMALL)
    centered_text(draw, (207, 64), "MAC", face=FONT_SMALL)
    centered_text(draw, (147, 119), "75%", face=FONT_SMALL)
    centered_text(draw, (207, 119), "60S", face=FONT_SMALL)
    return image


def state_color(state: str) -> tuple[int, int, int]:
    return {
        "needs_input": ACCENT_WARM,
        "ready": GOOD,
        "blocked": BAD,
        "offline": BAD,
        "idle": TEXT_DIM,
    }.get(state, ACCENT)


def draw_monitor(draw: ImageDraw.ImageDraw, state: str) -> None:
    signal = state_color(state)
    rect(draw, 10, 23, 36, 3, fill=LINE)
    rect(draw, 12, 57, 32, 2, fill=PANEL_DEEP)
    rect(draw, 7, 26, 42, 31, fill=PANEL_DEEP, outline=LINE, radius=4)
    rect(draw, 45, 33, 2, 12, fill=blend(PANEL_DEEP, signal, 48))
    screen = blend(BACKGROUND, signal, 18)
    rect(draw, 11, 31, 34, 18, fill=screen, outline=blend(LINE, signal, 66), radius=2)
    center_y = 40
    previous = center_y
    for offset in range(28):
        sample = (offset + NOW_MS // 70) % 12
        wave = {-1: 0, 2: -1, 3: -4, 4: 3, 5: 1}.get(sample, 0)
        y = center_y + wave
        if offset:
            draw.line((13 + offset - 1, previous, 13 + offset, y), fill=signal)
        previous = y
    draw.line((13, 46, 36, 46), fill=blend(screen, signal, 112))
    rect(draw, 40, 53, 3, 2, fill=signal)


def draw_conduits(draw: ImageDraw.ImageDraw, state: str) -> None:
    signal = state_color(state)
    tube_background = blend(BACKGROUND, signal, 18)
    for column, x in enumerate((87, 99)):
        rect(draw, x + 2, 19, 6, 3, fill=LINE)
        rect(draw, x, 22, 10, 65, fill=PANEL_DEEP, outline=LINE, radius=2)
        rect(draw, x + 2, 26, 6, 2, fill=PANEL)
        rect(draw, x + 2, 81, 6, 2, fill=PANEL)
        rect(draw, x + 3, 29, 4, 48, fill=tube_background,
             outline=blend(LINE, signal, 42))
        for packet in range(3):
            offset = (NOW_MS // 68 + column * 9 + packet * 19) % 58
            if offset <= 43:
                rect(draw, x + 4, 29 + offset, 2, 5,
                     fill=blend(tube_background, signal, 150))
        rect(draw, x + 4, 83, 3, 2, fill=signal)
        draw.line((x + 5, 87, x + 5, 93), fill=blend(LINE, signal, 70))
        draw.line((x + 5, 93, 103, 98), fill=blend(LINE, signal, 70))
    rect(draw, 100, 96, 7, 5, fill=PANEL_DEEP,
         outline=blend(LINE, signal, 70), radius=2)
    draw.line((103, 101, 99, 108), fill=blend(LINE, signal, 70))


def draw_platform(draw: ImageDraw.ImageDraw, state: str) -> None:
    signal = state_color(state)
    points_x = (-42, -40, -36, -30, -22, -12, 0, 12, 22, 30, 36, 40, 42)
    points_y = (0, 3, 5, 7, 9, 10, 10, 10, 9, 7, 5, 3, 0)
    for lift, amount in ((10, 45), (5, 78), (0, 112)):
        points = [(60 + x, 110 + y - lift) for x, y in zip(points_x, points_y)]
        draw.line(points, fill=blend(BACKGROUND, signal, amount), width=1)


def draw_quota(draw: ImageDraw.ImageDraw, y: int, label: str,
               remaining: int) -> None:
    draw.text((126, y + 1), label, font=FONT_MICRO, fill=WHITE)
    rect(draw, 164, y + 1, 68, 8, fill=BACKGROUND, outline=TEXT_DIM, radius=2)
    fill = max(1, 66 * remaining // 100)
    color = BAD if remaining < 10 else ACCENT_WARM if remaining < 30 else GOOD
    rect(draw, 165, y + 2, fill, 6, fill=color, radius=1)


def draw_detail() -> Image.Image:
    background = Image.open(
        ROOT / "docs" / "codex-dialog-pixel-background-240x135-v2.png"
    ).convert("RGBA")
    image = background.copy()
    draw = ImageDraw.Draw(image)
    draw_monitor(draw, "running")
    draw_conduits(draw, "running")
    draw.ellipse((29, 108, 83, 116), fill=PANEL_DEEP)
    paste_pet(image, "kRunning2", 6, 10, 100)
    draw_platform(draw, "running")
    draw_keyboard(draw, 6, 6, True)
    centered_text(draw, (60, 12), "2/4", face=FONT_MICRO)
    draw_battery(draw, 75, 7, 76, charging=True, compact=True)

    draw_angular_panel(draw, 122, 4, 114, 127)
    rect(draw, 124, 6, 110, 22, fill=BACKGROUND, radius=5)
    rect(draw, 124, 28, 110, 73, fill=BACKGROUND, outline=ACCENT, radius=5)
    draw.text((126, 9), "Improve device UI", font=FONT_TITLE, fill=WHITE)
    draw.text((126, 34), "Rendering current", font=FONT_BODY, fill=WHITE)
    draw.text((126, 51), "firmware screens", font=FONT_BODY, fill=WHITE)
    draw.text((126, 68), "for the docs", font=FONT_BODY, fill=WHITE)
    draw_quota(draw, 103, "WEEKLY", 68)
    draw_quota(draw, 116, "5H", 42)
    return image


def save_preview(image: Image.Image, name: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scaled = image.convert("RGB").resize(
        (WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST
    )
    scaled.save(OUTPUT / name, optimize=True)


def main() -> None:
    save_preview(draw_home(), "device-home.png")
    save_preview(draw_detail(), "codex-detail.png")
    print("Rendered docs/images/device-home.png and docs/images/codex-detail.png")


if __name__ == "__main__":
    main()
