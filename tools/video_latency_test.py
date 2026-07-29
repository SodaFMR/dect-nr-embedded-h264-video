"""Measure monitor-to-decoder latency through the complete DECT video path."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time
import tkinter as tk

import serial

try:
    from tools.h264_usb_receiver import (
        START_CODES,
        h264_nal_type,
        read_record,
    )
    from tools.video_metrics import (
        best_transition_matches,
        detect_luma_transitions,
        horizontal_contrast,
        percentile,
    )
except ModuleNotFoundError:
    from h264_usb_receiver import START_CODES, h264_nal_type, read_record
    from video_metrics import (
        best_transition_matches,
        detect_luma_transitions,
        horizontal_contrast,
        percentile,
    )


def annexb(payload: bytes) -> bytes:
    if payload.startswith(START_CODES):
        return payload
    return b"\x00\x00\x00\x01" + payload


def read_exact_pipe(stream, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return b""
        data.extend(chunk)
    return bytes(data)


def write_rows(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--width", type=int, default=1008)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--transitions", type=int, default=30)
    parser.add_argument("--dwell", type=float, default=0.8)
    parser.add_argument("--warmup", type=float, default=4.0)
    parser.add_argument("--tail", type=float, default=2.0)
    parser.add_argument("--output-dir", default="metrics/latency")
    return parser.parse_args()


def ffmpeg_decoder_command() -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-f",
        "h264",
        "-i",
        "pipe:0",
        "-pix_fmt",
        "gray",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_path = output_dir / "latency_stream.h264"
    ffmpeg_log_path = output_dir / "ffmpeg_errors.log"

    epoch = time.monotonic()
    stop_event = threading.Event()
    source_transitions: list[tuple[float, int]] = []
    decoded_samples: list[tuple[float, float]] = []
    transport = {"records": 0, "bytes": 0, "frame_nals": 0}

    ffmpeg_log = ffmpeg_log_path.open("wb")
    decoder = subprocess.Popen(
        ffmpeg_decoder_command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=ffmpeg_log,
        bufsize=0,
    )

    def receive_worker() -> None:
        sps: bytes | None = None
        pps: bytes | None = None
        synced = False
        assert decoder.stdin is not None
        try:
            with serial.Serial(args.port, args.baud, timeout=0.05) as uart, capture_path.open("wb") as capture:
                uart.reset_input_buffer()
                while not stop_event.is_set():
                    payload = read_record(uart, time.monotonic() + 0.5)
                    if payload is None:
                        continue
                    nal_type = h264_nal_type(payload)
                    transport["records"] += 1
                    transport["bytes"] += len(payload)
                    if nal_type in (1, 5):
                        transport["frame_nals"] += 1
                    if nal_type == 7:
                        sps = payload
                        continue
                    if nal_type == 8:
                        pps = payload
                        continue

                    chunks = [payload]
                    if not synced:
                        if nal_type != 5 or sps is None or pps is None:
                            continue
                        chunks = [sps, pps, payload]
                        synced = True
                    elif nal_type == 5:
                        chunks = [chunk for chunk in (sps, pps, payload) if chunk is not None]

                    for chunk in chunks:
                        encoded = annexb(chunk)
                        capture.write(encoded)
                        decoder.stdin.write(encoded)
                    decoder.stdin.flush()
        finally:
            try:
                decoder.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    def decode_worker() -> None:
        assert decoder.stdout is not None
        frame_size = args.width * args.height
        while True:
            frame = read_exact_pipe(decoder.stdout, frame_size)
            if not frame:
                break
            contrast = horizontal_contrast(frame, args.width, args.height)
            decoded_samples.append((time.monotonic() - epoch, contrast))

    receiver_thread = threading.Thread(target=receive_worker, name="serial-receiver", daemon=True)
    decoder_thread = threading.Thread(target=decode_worker, name="h264-decoder", daemon=True)
    receiver_thread.start()
    decoder_thread.start()

    root = tk.Tk()
    root.title("DECTmo latency pattern - ESC aborts")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, highlightthickness=0, borderwidth=0)
    canvas.pack(fill="both", expand=True)
    aborted_state = {"value": False}
    root.bind("<Escape>", lambda _event: aborted_state.__setitem__("value", True))
    root.update_idletasks()
    root.update()

    def show_pattern(state: int) -> None:
        width = root.winfo_width()
        height = root.winfo_height()
        left = "white" if state else "black"
        right = "black" if state else "white"
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width // 2, height, fill=left, outline=left)
        canvas.create_rectangle(width // 2, 0, width, height, fill=right, outline=right)
        canvas.create_text(
            width // 2,
            height // 2,
            text="DECTmo LATENCY TEST",
            fill="red",
            font=("Arial", 28, "bold"),
        )
        root.update_idletasks()
        root.update()

    show_pattern(0)

    def wait_with_events(duration: float) -> bool:
        end = time.monotonic() + duration
        while time.monotonic() < end and not aborted_state["value"]:
            root.update()
            time.sleep(0.005)
        return aborted_state["value"]

    aborted = False
    try:
        aborted = wait_with_events(args.warmup)

        state = 0
        for _ in range(args.transitions):
            if aborted:
                break
            state ^= 1
            show_pattern(state)
            source_transitions.append((time.monotonic() - epoch, state))
            aborted = wait_with_events(args.dwell)

        if not aborted:
            aborted = wait_with_events(args.tail)
    finally:
        root.destroy()
        stop_event.set()
        receiver_thread.join(timeout=3.0)
        if receiver_thread.is_alive():
            decoder.terminate()
        decoder_thread.join(timeout=3.0)
        try:
            decoder.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            decoder.kill()
            decoder.wait()
        ffmpeg_log.close()

    threshold, observed_transitions = detect_luma_transitions(decoded_samples, min_stable_frames=2)
    orientation, matches = best_transition_matches(source_transitions, observed_transitions)
    latencies = [float(item["latency_ms"]) for item in matches]
    duration = max((sample[0] for sample in decoded_samples), default=0.0)
    summary = {
        "port": args.port,
        "baud": args.baud,
        "resolution": f"{args.width}x{args.height}",
        "aborted": aborted,
        "source_transitions": len(source_transitions),
        "observed_transitions": len(observed_transitions),
        "matched_transitions": len(matches),
        "decoded_frames": len(decoded_samples),
        "records": transport["records"],
        "received_bytes": transport["bytes"],
        "frame_nals": transport["frame_nals"],
        "measurement_duration_s": round(duration, 3),
        "received_fps": round(len(decoded_samples) / duration, 3) if duration > 0 else 0.0,
        "bitrate_kbps": round(transport["bytes"] * 8 / duration / 1000, 3) if duration > 0 else 0.0,
        "contrast_threshold": round(threshold, 3),
        "camera_orientation": orientation,
        "latency_ms_min": round(min(latencies), 3) if latencies else None,
        "latency_ms_mean": round(statistics.mean(latencies), 3) if latencies else None,
        "latency_ms_median": round(statistics.median(latencies), 3) if latencies else None,
        "latency_ms_stdev": round(statistics.pstdev(latencies), 3) if latencies else None,
        "latency_ms_p95": round(percentile(latencies, 0.95), 3) if latencies else None,
        "latency_ms_max": round(max(latencies), 3) if latencies else None,
        "timing_uncertainty_ms": 16.67,
    }

    write_rows(output_dir / "source_transitions.csv", ["time_s", "state"], source_transitions)
    write_rows(output_dir / "decoded_contrast.csv", ["time_s", "horizontal_contrast"], decoded_samples)
    write_rows(output_dir / "observed_transitions.csv", ["time_s", "state"], observed_transitions)
    write_rows(
        output_dir / "latency_matches.csv",
        ["source_time_s", "observed_time_s", "state", "latency_ms"],
        (
            (
                item["source_time_s"],
                item["observed_time_s"],
                item["state"],
                item["latency_ms"],
            )
            for item in matches
        ),
    )
    (output_dir / "latency_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0 if len(matches) >= max(10, len(source_transitions) // 2) else 2


if __name__ == "__main__":
    raise SystemExit(main())
