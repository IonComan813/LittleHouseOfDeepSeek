"""The live window, inside the house process itself (one process, one renderer).

Nothing is drawn while the window is closed: the still picture for
``house_glance`` renders a single frame on demand. Opening the window (from
DSH via config, from ``view.bat``, or ``POST /window``) starts an animated
loop on the main thread; closing it stops all drawing while the house keeps
running and she keeps living. The window is read-only: input is ignored.
Each frame draws her as she is at that moment (``anim.current_pose``).
"""

from __future__ import annotations

import os
import threading
import time

FPS_ACTIVE = 12  # while she is walking / doing something
FPS_IDLE = 4  # waves and rain only


def pygame_available() -> bool:
    try:
        import pygame  # noqa: F401
    except ImportError:
        return False
    return True


class Display:
    def __init__(self, house, scale: int = 2) -> None:
        self.house = house
        self.scale = scale
        self.want_open = False
        self.is_open = False
        self._wake = threading.Event()

    def request(self, open_: bool, scale: int | None = None) -> None:
        if scale:
            self.scale = max(1, min(4, int(scale)))
        self.want_open = open_
        self._wake.set()

    def run(self, stop: threading.Event) -> None:
        """Main-thread loop. Returns when ``stop`` is set."""
        screen = None
        clock = None
        while not stop.is_set():
            if self.want_open and screen is None:
                screen, clock = self._open()
            elif not self.want_open and screen is not None:
                screen = self._close()
            if screen is None:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            import pygame

            from . import render
            from .anim import current_pose

            for event in pygame.event.get():  # read-only: only closing is honoured
                if event.type == pygame.QUIT:
                    self.want_open = False
            now = time.time()
            with self.house.lock:
                pose = current_pose(self.house.world)
                frame = render.render(self.house.world, now, pose)
            pygame.transform.scale(frame, screen.get_size(), screen)
            pygame.display.flip()
            busy = pose.walking or pose.effect is not None
            clock.tick(FPS_ACTIVE if busy else FPS_IDLE)
        if screen is not None:
            self._close()

    def _open(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        from . import scene as S

        pygame.display.init()  # video only: no audio device needed
        size = (S.COLS * S.TILE * self.scale, (S.ROWS * S.TILE + S.HUD_H) * self.scale)
        screen = pygame.display.set_mode(size)
        pygame.display.set_caption("潮汐湾小屋（只读）")
        self.is_open = True
        return screen, pygame.time.Clock()

    def _close(self):
        import pygame

        pygame.display.quit()
        self.is_open = False
        return None
