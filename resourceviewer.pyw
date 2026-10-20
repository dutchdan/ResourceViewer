# -*- coding: utf-8 -*-
"""ResourceViewer HUD — Strata engine + system resource monitor.

Borderless, always-on-top, drag-anywhere HUD. Polls http://127.0.0.1:8080/metrics
once per second. Pure Python stdlib. See SPEC.md.
"""

import json
import math
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.request
from pathlib import Path

try:  # Pillow: antialiased rings/background via 4x supersampling
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False
SERVER = "http://127.0.0.1:8080"
POLL_S = 1.0
GIB = 1024 ** 3

# ---- style ------------------------------------------------------------------
BG = "#101418"
KEY = "#010203"          # transparency colour-key for rounded corners
FG = "#E8EAED"
DIM = "#9AA0A6"
GREEN = "#34C759"
RED = "#FF3B30"
GRAY_SQ = "#3A4048"      # offline squares
MARGIN = 2               # corner-rounding margin

FONT = "Segoe UI"
F_POWER = (FONT, 26, "bold")
F_UNIT = (FONT, 12)
F_TEMP = (FONT, 18, "bold")
F_TPS = (FONT, 22, "bold")
F_TPS_U = (FONT, 11)
F_PCT = (FONT, 13, "bold")
F_LABEL = (FONT, 12, "bold")
F_OFF = (FONT, 9, "bold")

# ---- geometry ---------------------------------------------------------------
S, GAP = 9, 2                    # square size / gap
COLS = 4
RAM_ROWS = 16
VRAM_ROWS = 8
GRID_W = COLS * S + (COLS - 1) * GAP          # 42
RAM_H = RAM_ROWS * S + (RAM_ROWS - 1) * GAP   # 174
VRAM_H = VRAM_ROWS * S + (VRAM_ROWS - 1) * GAP

W, H = 260, 376
RAM_X = 24
VRAM_X = W - 24 - GRID_W
CX_CPU = RAM_X + GRID_W // 2          # aligned under RAM grid
CX_CTX = W // 2
CX_GPU = VRAM_X + GRID_W // 2         # aligned under VRAM grid
CY = H - 45                                   # circle centre y
R, RING = 30, 6                               # green ring stroke
RING_RED = 9                                  # red arc fatter so no green shines past it
LABEL_Y = CY - R - 14
GRID_BOTTOM = LABEL_Y - 10
POWER_Y, UNIT_Y = 46, 70
TEMP_X = VRAM_X + GRID_W // 2                 # gpu temp sits above the VRAM grid
TEMP_Y = 158
TEMP_UY = 176
TPS_Y = 242                                   # t/s number sits above CTX
TPS_UY = 264

STATE_PATH = Path(os.getenv("APPDATA", ".")) / "ResourceViewer" / "state.json"


# ---- data fetch -------------------------------------------------------------
def fetch(url, timeout=1.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def poller(out):
    import time
    while True:
        try:
            out.put(("ok", fetch(SERVER + "/metrics")))
        except Exception:
            out.put(("err", None))
        time.sleep(POLL_S)


# ---- helpers ----------------------------------------------------------------
def fmt_tps(v):
    return str(int(round(v)))


class HUD:
    def __init__(self):
        if sys.platform == "win32":
            import ctypes
            # single instance: hold a named mutex for process lifetime
            self._mutex = ctypes.windll.kernel32.CreateMutexW(
                None, False, "Local\\ResourceViewer_HUD")
            if ctypes.windll.kernel32.GetLastError() == 183:  # already exists
                sys.exit(0)
            try:  # DPI aware (system aware)
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        self.cfg = {"x": None, "y": None, "topmost": True, "alpha": 0.95}
        self._load_cfg()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-transparentcolor", KEY)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.attributes("-topmost", self.cfg["topmost"])
        self.root.configure(bg=KEY)

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.cfg["x"] if self.cfg["x"] is not None else sw - W - 40
        y = self.cfg["y"] if self.cfg["y"] is not None else 40
        self.root.geometry(f"{W}x{H}+{x}+{y}")

        self.cv = tk.Canvas(self.root, width=W, height=H, bg=KEY,
                            highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        self._drag = None
        self.cv.bind("<ButtonPress-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.cv.bind("<ButtonRelease-1>", self._drag_end)
        self.cv.bind("<Button-3>", self._menu)

        self._build_menu()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.q = queue.Queue()
        threading.Thread(target=poller, args=(self.q,), daemon=True).start()

        self.last = None
        self.offline = False
        self._imgs = []
        self._ring_cache = {}
        self.root.after(300, self._drain)
        self.root.mainloop()

    # -- config --------------------------------------------------------------
    def _load_cfg(self):
        try:
            self.cfg.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass

    def _save_cfg(self):
        try:
            g = self.root.winfo_geometry().split("+")
            self.cfg["x"], self.cfg["y"] = int(g[1]), int(g[2])
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self.cfg), encoding="utf-8")
        except Exception:
            pass

    # -- window --------------------------------------------------------------
    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, _):
        self._drag = None
        self._save_cfg()

    def _build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        op = tk.Menu(m, tearoff=0)
        for pct in (80, 95, 100):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self._set_alpha(p / 100))
        m.add_cascade(label="Opacity", menu=op)
        m.add_command(label="Toggle always-on-top", command=self._toggle_top)
        m.add_command(label="Reset position", command=self._reset_pos)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        self.menu = m

    def _menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def _set_alpha(self, a):
        self.cfg["alpha"] = a
        self.root.attributes("-alpha", a)
        self._save_cfg()

    def _toggle_top(self):
        self.cfg["topmost"] = not self.cfg["topmost"]
        self.root.attributes("-topmost", self.cfg["topmost"])
        self._save_cfg()

    def _reset_pos(self):
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw - W - 40}+40")
        self._save_cfg()

    def quit(self):
        self._save_cfg()
        self.root.destroy()

    # -- drawing -------------------------------------------------------------
    def _round(self):
        if HAS_PIL:
            SS = 4
            im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([MARGIN * SS, MARGIN * SS,
                                 (W - MARGIN) * SS, (H - MARGIN) * SS],
                                radius=10 * SS, fill=BG)
            im = im.resize((W, H), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            self._imgs.append(ph)
            self.cv.create_image(W // 2, H // 2, image=ph)
            return
        c = self.cv
        r = 10
        pts = [
            MARGIN + r, MARGIN, W - MARGIN - r, MARGIN,
            W - MARGIN, MARGIN, W - MARGIN, MARGIN + r,
            W - MARGIN, H - MARGIN - r, W - MARGIN, H - MARGIN,
            W - MARGIN - r, H - MARGIN, MARGIN + r, H - MARGIN,
            MARGIN, H - MARGIN, MARGIN, H - MARGIN - r,
            MARGIN, MARGIN + r, MARGIN, MARGIN,
        ]
        c.create_polygon(pts, smooth=True, fill=BG, outline=BG)

    def _grid(self, x, bottom, rows, total, used):
        col = GRAY_SQ if self.offline else RED
        green = GRAY_SQ if self.offline else GREEN
        for i in range(total):
            row, c_ = divmod(i, COLS)
            if row >= rows:
                break
            sx = x + c_ * (S + GAP)
            sy = bottom - (row + 1) * S - row * GAP
            self.cv.create_rectangle(sx, sy, sx + S, sy + S,
                                     outline="", fill=col if i < used else green)

    def _ring_img(self, frac, track):
        key = (track, round(frac * 200))
        img = self._ring_cache.get(key)
        if img is None:
            SS = 4
            r_out = R + RING_RED / 2 + 1
            side = int(2 * r_out * SS)
            im = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            r = R * SS
            box = [side / 2 - r, side / 2 - r, side / 2 + r, side / 2 + r]
            d.ellipse(box, outline=track, width=RING * SS)
            if frac > 0.003:
                ext = frac * 360          # PIL: clockwise, 0 deg = 3 o'clock
                d.arc(box, start=90, end=90 + ext, fill=RED, width=RING_RED * SS)
            im = im.resize((int(side / SS) + 1,) * 2, Image.LANCZOS)
            img = ImageTk.PhotoImage(im)
            self._ring_cache[key] = img
        return img

    def _circle(self, cx, cy, frac, text):
        c = self.cv
        track = GRAY_SQ if self.offline else GREEN
        frac = max(0.0, min(1.0, frac))
        if HAS_PIL:
            c.create_image(cx, cy, image=self._ring_img(frac, track))
        else:
            c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=track,
                          width=RING, fill="")
            if frac > 0.003 and not self.offline:
                ext = frac * 360
                c.create_arc(cx - R, cy - R, cx + R, cy + R, style="arc",
                             outline=RED, width=RING_RED, start=270 - ext,
                             extent=ext)
        c.create_text(cx, cy, text=text, fill=DIM if self.offline else FG,
                      font=F_PCT)

    def _text(self, x, y, s, font, fill):
        self.cv.create_text(x, y, text=s, fill=fill, font=font)

    def render(self, d):
        c = self.cv
        c.delete("all")
        self._imgs = []
        self._round()

        hw = d.get("hardware") or {}
        eng = d.get("engine") or {}
        live = d.get("live") or {}
        reqs = d.get("requests") or []
        last = reqs[0] if reqs else {}

        # power
        pw = hw.get("gpu_power")
        ncol = DIM if self.offline else FG      # all numbers share one colour
        if pw is not None:
            self._text(W // 2, POWER_Y, str(int(round(pw))), F_POWER, ncol)
        self._text(W // 2, UNIT_Y, "W", F_UNIT, DIM)

        # grids (1 square = 1 GiB, red fills bottom-up, left->right in row)
        rt, ru = hw.get("ram_total"), hw.get("ram_used")
        if rt:
            self._grid(RAM_X, GRID_BOTTOM, RAM_ROWS,
                       min(math.ceil(rt / GIB), COLS * RAM_ROWS),
                       max(0, round((ru or 0) / GIB)))
        vt, vu = hw.get("gpu_mem_total"), hw.get("gpu_mem_used")
        if vt:
            self._grid(VRAM_X, GRID_BOTTOM, VRAM_ROWS,
                       min(math.ceil(vt / GIB), COLS * VRAM_ROWS),
                       max(0, round((vu or 0) / GIB)))

        # gpu temp above the VRAM grid (red when hot)
        temp = hw.get("gpu_temp")
        if temp is not None and not self.offline:
            tcol = RED if temp >= 80 else ncol
            self._text(TEMP_X, TEMP_Y, str(int(round(temp))), F_TEMP, tcol)
            self._text(TEMP_X, TEMP_UY, "°C", F_TPS_U, DIM)

        # tok/s: big number centred, unit underneath (live, else last decode)
        tps = None
        if not self.offline:
            if hw.get("tok_s"):
                tps = hw["tok_s"]
            elif last.get("decode_tok_s"):
                tps = last["decode_tok_s"]
        if tps is not None:
            self._text(W // 2, TPS_Y, fmt_tps(tps), F_TPS, ncol)
            self._text(W // 2, TPS_UY, "t/s", F_TPS_U, DIM)

        # circles
        for cx, lab, frac in (
            (CX_CPU, "CPU", (hw.get("cpu") or 0) / 100),
            (CX_CTX, "CTX", (live.get("prompt_total") or last.get("prompt_total") or 0)
                           / max(1, eng.get("max_context") or 1)),
            (CX_GPU, "GPU", (hw.get("gpu_util") or 0) / 100),
        ):
            self._text(cx, LABEL_Y, lab, F_LABEL, DIM)
            self._circle(cx, CY, frac, f"{round(frac * 100)}%")

        if self.offline:
            self._text(MARGIN + 12, MARGIN + 10, "offline", F_OFF, DIM)

    # -- main loop ------------------------------------------------------------
    def _drain(self):
        try:
            got = False
            try:
                while True:
                    kind, data = self.q.get_nowait()
                    if kind == "ok":
                        if not isinstance(data, dict) or "hardware" not in data:
                            continue
                        self.offline = False
                        self.last = data
                    else:
                        if self.last is not None:
                            self.offline = True
                    got = True
            except queue.Empty:
                pass
            if got and self.last is not None:
                sig = json.dumps(self.last.get("hardware", {}), sort_keys=True) + \
                      json.dumps([self.last.get("live"),
                                  self.last.get("requests", [])[:1], self.offline])
                if sig != getattr(self, "_sig", None):
                    self._sig = sig
                    self.render(self.last)
        except Exception:
            self._log_exc()
        finally:
            # always keep the chain alive, even if render blew up
            self.root.after(1000, self._drain)

    def _log_exc(self):
        import traceback
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_PATH.parent / "error.log", "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass


if __name__ == "__main__":
    HUD()
