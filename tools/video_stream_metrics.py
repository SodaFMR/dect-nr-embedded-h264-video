"""Capture and summarize the received DECT H.264 stream."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time

import serial

try:
    from tools.h264_usb_receiver import (
        START_CODES,
        h264_nal_type,
        read_record,
    )
    from tools.video_metrics import summarize_stream_records
except ModuleNotFoundError:
    from h264_usb_receiver import START_CODES, h264_nal_type, read_record
    from video_metrics import summarize_stream_records


def annexb(payload: bytes) -> bytes:
    if payload.startswith(START_CODES):
        return payload
    return b"\x00\x00\x00\x01" + payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--output-dir", default="metrics/video_stream")
    return parser.parse_args()


def analyze_capture(path: Path) -> tuple[dict[str, object], str]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "h264",
            "-count_frames",
            "-show_entries",
            "stream=codec_name,profile,width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    stream = {}
    if probe.returncode == 0:
        streams = json.loads(probe.stdout).get("streams", [])
        if streams:
            stream = streams[0]

    null_output = "NUL" if os.name == "nt" else "/dev/null"
    decode = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "warning",
            "-f",
            "h264",
            "-i",
            str(path),
            "-f",
            "null",
            null_output,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    decode_log = decode.stderr
    analysis = {
        "codec": stream.get("codec_name"),
        "profile": stream.get("profile"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "decoded_frames": int(stream.get("nb_read_frames", 0) or 0),
        "decoder_corrupt_frames": decode_log.count("corrupt decoded frame"),
        "decoder_errors": decode_log.count("error while decoding"),
    }
    return analysis, decode_log


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stream_path = output_dir / "stream.h264"
    records_path = output_dir / "records.csv"
    summary_path = output_dir / "summary.json"
    decode_log_path = output_dir / "decoder.log"

    records: list[tuple[float, int, int]] = []
    start = time.monotonic()
    end = start + args.duration
    sps: bytes | None = None
    pps: bytes | None = None
    synced = False

    with (
        serial.Serial(args.port, args.baud, timeout=0.01) as uart,
        stream_path.open("wb") as stream,
    ):
        uart.reset_input_buffer()
        while time.monotonic() < end:
            payload = read_record(uart, min(end, time.monotonic() + 0.5))
            if payload is None:
                continue
            timestamp = time.monotonic() - start
            nal_type = h264_nal_type(payload)
            if nal_type is None:
                continue
            records.append((timestamp, nal_type, len(payload)))

            if nal_type == 7:
                sps = payload
                continue
            if nal_type == 8:
                pps = payload
                continue
            if not synced:
                if nal_type != 5 or sps is None or pps is None:
                    continue
                for chunk in (sps, pps, payload):
                    stream.write(annexb(chunk))
                synced = True
            else:
                if nal_type == 5:
                    if sps is not None:
                        stream.write(annexb(sps))
                    if pps is not None:
                        stream.write(annexb(pps))
                stream.write(annexb(payload))

    summary = summarize_stream_records(records)
    analysis, decode_log = analyze_capture(stream_path)
    summary.update(analysis)
    summary.update(
        {
            "port": args.port,
            "baud": args.baud,
            "requested_duration_s": args.duration,
        }
    )

    with records_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s", "nal_type", "payload_bytes"])
        writer.writerows(records)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    decode_log_path.write_text(decode_log, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
