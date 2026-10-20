# ResourceViewer

A tiny borderless, always-on-top desktop HUD that shows Strata engine + system
resource stats in real time — RAM/VRAM grids, CPU / context / GPU rings,
tok/s, GPU power draw and temperature.

Single-file Python app (`resourceviewer.pyw`), no console window, negligible
footprint (< 30 MB RAM, ~0 % CPU, one HTTP request per second).

## What it shows

| Element | Source field (`GET /metrics`) |
|---|---|
| RAM grid (4×16 squares, 1 GiB each) | `hardware.ram_used / ram_total` |
| VRAM grid (4×8 squares) | `hardware.gpu_mem_used / gpu_mem_total` |
| CPU ring | `hardware.cpu` |
| CTX ring (LLM context usage) | `live.prompt_total` ÷ `engine.max_context` |
| GPU ring | `hardware.gpu_util` |
| tok/s | `hardware.tok_s`, else last request's `decode_tok_s` |
| Power (W) | `hardware.gpu_power` |
| GPU temp (red at ≥ 80 °C) | `hardware.gpu_temp` |

Red squares fill bottom-up; green means free. Rings: full green track, red arc
grows clockwise from 6 o'clock.

## Requirements

- **Python 3.10+** (tested on 3.14) with `tkinter` — that's all you need.
- **Pillow** (optional) — enables antialiased rings and rounded corners.
  Without it the app falls back to plain Tk drawing.
- A Strata-style server exposing `http://127.0.0.1:8080/metrics`
  (URL is a constant at the top of the file).

## Run

```
pythonw resourceviewer.pyw
```

On Windows, name it `.pyw` and double-click (or make a shortcut to
`pythonw.exe resourceviewer.pyw`) to launch without a console window.
A named mutex keeps it single-instance — launching twice just exits quietly.

## Controls

- **Drag** anywhere to move the window.
- **Right-click** menu: opacity (80 / 95 / 100 %), toggle always-on-top,
  reset position, quit.
- Position, opacity and topmost are persisted to
  `%APPDATA%\ResourceViewer\state.json`.

## Design notes

The full spec (layout, styling, grid-fill rules, update-loop design, error
handling) lives in [SPEC.md](SPEC.md).

## License

MIT (see [LICENSE](LICENSE)).
