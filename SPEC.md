# ResourceViewer — Specification v1.0 (as built)

A borderless, always-on-top desktop HUD showing Strata engine + system resources in real time.
Implemented in `resourceviewer.pyw` (single file, ~330 lines).

## 1. Goals
- Single small window on the desktop: RAM grid, VRAM grid, CPU %, context %, GPU load %,
  tok/s, GPU power draw, GPU temperature.
- Negligible cost: < 30 MB RAM, ~0% CPU (redraw on change only), one HTTP request per second.

## 2. Data source
- Poll `GET http://127.0.0.1:8080/metrics` once per second (1 s timeout), no auth.
- Fields used:

| HUD element | JSON path |
|---|---|
| RAM grid | `hardware.ram_used`, `hardware.ram_total` |
| VRAM grid | `hardware.gpu_mem_used`, `hardware.gpu_mem_total` |
| CPU circle | `hardware.cpu` (0–100) |
| Context circle | `live.prompt_total` while active, else latest `requests[0].prompt_total`, ÷ `engine.max_context` |
| GPU circle | `hardware.gpu_util` |
| tok/s | `hardware.tok_s` (live), else last `requests[0].decode_tok_s` |
| Power | `hardware.gpu_power` |
| Temp | `hardware.gpu_temp` |

## 3. Window / HUD behaviour
- `overrideredirect(True)` — borderless, no taskbar entry; `-topmost` on by default.
- Size **260 × 376 px**, rounded corners (Pillow AA image; Tk fallback is a smoothed polygon).
- **Single instance**: named mutex `Local\ResourceViewer_HUD`; a second launch exits silently.
- **Drag** anywhere to move; **right-click** menu: Opacity (80/95/100%), Toggle always-on-top,
  Reset position, Quit.
- Position, opacity and topmost persisted to `%APPDATA%\ResourceViewer\state.json`;
  default top-right of primary monitor. DPI aware (`SetProcessDpiAwareness(1)`).
- Opacity default **95%**.

## 4. Layout (final)
```
┌──────────────────┐
│       76         │  power: 26 pt bold, "W" below (dim)
│       W          │
│      RAM    33   │  temp above VRAM grid: 18 pt, "°C" below;
│       ▫▫    °C   │  turns RED at >= 80 °C
│       ▫▫   ▫▫▫▫  │  VRAM grid 4×8 (right)
│ 153   ▫▫   ▫▫▫▫  │  tok/s: 22 pt bold, "t/s" below (dim)
│ t/s   ▫▫         │  RAM grid 4×16 (left)
│       CPU  CTX GPU  labels: 12 pt bold, centred under grid/circle
│       ◯    ◯   ◯    circles ⌀60 px
└──────────────────┘
```
- Columns: **left** RAM→CPU, **middle** power→tok/s→CTX, **right** temp→VRAM→GPU.
- Squares: 9 px, 3 px gap (compact). Circles: radius 30.

## 5. Visual style
- Dark: background `#101418`, text/numbers `#E8EAED`, dim labels `#9AA0A6`.
- Font: **Segoe UI** (bold numbers, regular units).
- Squares: free green `#34C759`, used red `#FF3B30`.
- **Circles**: full green ring (stroke 6); red arc (stroke 9, fatter so no green fringes)
  rides on top of the green and *replaces* it, growing **clockwise from 6 o'clock**.
  0% = pure green ring. Percentage text centred inside, same colour as all other numbers.
- **Anti-aliasing**: rings + rounded background rendered via Pillow at 4× supersampling,
  LANCZOS downscale; ring images cached per fill level. Without Pillow, falls back to
  plain Tk drawing.
- Server down: all grey (`#3A4048` squares, `#9AA0A6` text), "offline" tag top-left,
  data frozen at last good poll.

## 6. Grid fill rules
- 1 square = 1 GiB. RAM: `ceil(ram_total/1 GiB)` → 64 (4×16). VRAM: → 32 (4×8).
- Used count = `round(used / 1 GiB)`, clamped; fill bottom row → top, left → right in row.
- Non-multiple-of-4 totals: top row's missing cells not rendered.

## 7. Update loop
- Daemon thread fetches JSON; result posted to Tk via `queue.Queue` drained by
  `root.after` (no cross-thread widget access). Poll `POLL_S = 1.0` (constant at top).
- Redraw only when displayed values actually change (signature string compare).
- **Fault tolerance**: poll thread and UI refresh chain must never die silently — each
  cycle is wrapped in try/except/finally and the `after` re-arm happens in `finally`.
  Any unexpected exception is appended to `%APPDATA%\ResourceViewer\error.log`
  (with traceback) instead of vanishing into the `pythonw` void.

## 8. Launch / install
- `resourceviewer.pyw` + desktop shortcut **ResourceViewer** →
  `pythonw.exe resourceviewer.pyw` (icons: `resourceviewer.ico`, 16–256 px,
  black rounded tile with the little squares, red bottom-up).
- If the shortcut icon looks stale: clear `%LOCALAPPDATA%\IconCache.db` and
  `%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache*`, restart Explorer.

## 9. Dependencies
- Python 3.14 stdlib (tkinter, urllib, ctypes) — required.
- Pillow — optional, enables antialiased rings/corners.

## 10. Out of scope (possible future)
- History graphs/sparklines, temperature alarm sound, PyInstaller exe build,
  autostart flag, taskbar mode (needs an icon on the Tk window).
