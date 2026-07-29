"""Display a repeatable high-detail moving pattern for video stress tests."""

from __future__ import annotations

import argparse
import time
import tkinter as tk


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--cell", type=int, default=48)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    root.title("DECTmo dynamic video test - ESC aborts")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, highlightthickness=0, borderwidth=0)
    canvas.pack(fill="both", expand=True)
    aborted = {"value": False}
    root.bind("<Escape>", lambda _event: aborted.__setitem__("value", True))
    root.update_idletasks()
    root.update()

    start = time.monotonic()
    frame = 0
    interval = 1.0 / max(1.0, args.fps)
    next_frame = start

    try:
        while not aborted["value"] and time.monotonic() - start < args.duration:
            now = time.monotonic()
            if now < next_frame:
                root.update()
                time.sleep(min(0.005, next_frame - now))
                continue

            width = root.winfo_width()
            height = root.winfo_height()
            cell = max(16, args.cell)
            offset = (frame * max(2, cell // 5)) % (cell * 2)
            canvas.delete("all")
            row = 0
            y = -cell
            while y < height + cell:
                column = 0
                x = -cell * 2 + offset
                while x < width + cell:
                    color = "white" if (row + column + frame // 3) % 2 else "black"
                    canvas.create_rectangle(
                        x,
                        y,
                        x + cell,
                        y + cell,
                        fill=color,
                        outline=color,
                    )
                    x += cell
                    column += 1
                y += cell
                row += 1

            bar_x = (frame * 23) % max(1, width)
            canvas.create_rectangle(bar_x, 0, min(width, bar_x + 24), height, fill="red", outline="red")
            canvas.create_text(
                width // 2,
                height // 2,
                text=f"DECTmo DYNAMIC TEST  {frame:04d}",
                fill="red",
                font=("Arial", 28, "bold"),
            )
            root.update_idletasks()
            root.update()
            frame += 1
            next_frame += interval
    finally:
        root.destroy()

    print(f"frames_displayed={frame} duration_s={time.monotonic() - start:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
