"""產生托盤圖示（64x64，Windows 會自動縮小）。

版面：上方是「目前用量剩餘 %」的大數字，下方兩條細條：
  上條 = 目前（短窗口）剩餘，下條 = 每週剩餘。
顏色依剩餘量變化（綠／黃／紅）。繪圖概念借鏡 usage-monitor-for-claude（MIT）。
"""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .logic import LEVEL_CRIT, LEVEL_OK, level

SIZE = 64
BAR_H, BAR_GAP = 9, 3

GREEN, YELLOW, RED = (84, 201, 124, 255), (242, 190, 64, 255), (236, 84, 84, 255)
LEVEL_COLOR = {LEVEL_OK: GREEN, "warn": YELLOW, LEVEL_CRIT: RED}

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int):
    """找出放得進 max_w x max_h 的最大字體。"""
    for size in range(44, 11, -2):
        f = _font(size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= max_w and b - t <= max_h:
            return f, (l, t, r, b)
    f = _font(12)
    return f, draw.textbbox((0, 0), text, font=f)


def render_icon(
    session_remaining: Optional[float],
    weekly_remaining: Optional[float],
    *, light_taskbar: bool = False, stale: bool = False, symbol: str = "", show_used: bool = True,
) -> Image.Image:
    """session_remaining / weekly_remaining 為 0~100 的「剩餘 %」。
    兩者皆為 None 時畫 symbol（例如 '!' 或 '?'）。"""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fg = (30, 30, 30, 255) if light_taskbar else (245, 245, 245, 255)
    track = (0, 0, 0, 70) if light_taskbar else (255, 255, 255, 60)
    if stale:
        fg = (fg[0], fg[1], fg[2], 150)

    if session_remaining is None and weekly_remaining is None:
        f, (l, t, r, b) = _fit_text(d, symbol or "?", SIZE - 8, SIZE - 8)
        d.text(((SIZE - (r - l)) / 2 - l, (SIZE - (b - t)) / 2 - t), symbol or "?",
               font=f, fill=(236, 84, 84, 255) if symbol == "!" else (160, 160, 160, 255))
        return img

    top = session_remaining if session_remaining is not None else weekly_remaining
    top_shown = (100 - top) if show_used else top
    text = f"{round(top_shown):d}"
    f, (l, t, r, b) = _fit_text(d, text, SIZE - 2, SIZE - 2 * BAR_H - BAR_GAP - 6)
    d.text(((SIZE - (r - l)) / 2 - l, 1 - t), text, font=f, fill=fg)

    y2 = SIZE - BAR_H
    y1 = y2 - BAR_GAP - BAR_H
    for y, val in ((y1, session_remaining), (y2, weekly_remaining)):
        d.rectangle([0, y, SIZE - 1, y + BAR_H - 1], fill=track)
        if val is None:
            continue
        shown = (100 - val) if show_used else val
        w = max(0, min(SIZE, round(SIZE * shown / 100)))
        if w > 0:
            col = LEVEL_COLOR[level(val)]
            if stale:
                col = (col[0], col[1], col[2], 140)
            d.rectangle([0, y, w - 1, y + BAR_H - 1], fill=col)
    return img
