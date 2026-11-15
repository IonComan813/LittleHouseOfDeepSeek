"""Development only: rebuild the Chinese glyphs of the picture's bottom bar.

    /opt/lh/venv/bin/python tools/hud_glyphs.py [path/to/wqy-zenhei.ttc]

The bar needs only a few dozen characters (weather, seasons, 贝币, 饱腹值, the
cat's name + 亲密度). Instead of shipping a whole CJK font they are rendered
once, from the 12 px bitmap strike of WenQuanYi Zen Hei Sharp (文泉驿点阵正黑),
into house/littlehouse/assets/fonts/hud_glyphs.png (one 12x13 cell per
character, white on transparent) with the characters in hud_glyphs.txt.
Run it again after adding text to the bar (render.HUD_TEXT).
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "house"))
import pygame  # noqa: E402
import pygame.freetype as ft  # noqa: E402

from littlehouse import render  # noqa: E402

font_path = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
out_dir = os.path.join(os.path.dirname(render.__file__), "assets", "fonts")
chars = "".join(dict.fromkeys(c for c in "".join(render.HUD_TEXT) if ord(c) > 0x2E7F))
ft.init()
font = ft.Font(font_path, 12, font_index=1)  # index 1 = the "Sharp" face with bitmap strikes
font.antialiased = False
cw, ch = render.HUD_GLYPH
sheet = pygame.Surface((cw * len(chars), ch), pygame.SRCALPHA)
for i, c in enumerate(chars):
    glyph, rect = font.render(c, (255, 255, 255))
    sheet.blit(glyph, (i * cw + (cw - rect.width) // 2, font.get_sized_ascender() - rect.top))
pygame.image.save(sheet, os.path.join(out_dir, "hud_glyphs.png"))
with open(os.path.join(out_dir, "hud_glyphs.txt"), "w", encoding="utf-8") as f:
    f.write(chars + "\n")
print(len(chars), "glyphs:", chars)
