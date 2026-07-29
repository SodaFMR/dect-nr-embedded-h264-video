"""Receive framed H.264 records from the ESP32-P4 USB serial console."""

from __future__ import annotations

import argparse
from collections import Counter
import os
import subprocess
import sys
import time

import serial
from serial.tools import list_ports


MAGICS = (b"H4F1", b"H4D1")
MAX_MAGIC_LEN = max(len(magic) for magic in MAGICS)
START_CODES = (b"\x00\x00\x00\x01", b"\x00\x00\x01")
ANNEXB_SYNC_NALS = {7}
MAX_RECORD_SIZE = 256_000


def list_serial_ports() -> int:
    for port in list_ports.comports():
        print(f"{port.device} - {port.description} {port.hwid}")
    return 0


def read_exact(uart: serial.Serial, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = uart.read(size - len(data))
        if not chunk:
            continue
        data.extend(chunk)
    return bytes(data)


def decode_record_size(raw: bytes) -> int:
    little = int.from_bytes(raw, "little")
    if 0 < little <= MAX_RECORD_SIZE:
        return little
    big = int.from_bytes(raw, "big")
    if 0 < big <= MAX_RECORD_SIZE:
        return big
    return 0


def read_record(uart: serial.Serial, deadline: float | None = None) -> bytes | None:
    window = bytearray()
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return None
        byte = uart.read(1)
        if not byte:
            continue
        window.extend(byte)
        if len(window) > MAX_MAGIC_LEN:
            del window[0 : len(window) - MAX_MAGIC_LEN]
        if bytes(window) in MAGICS:
            size = decode_record_size(read_exact(uart, 4))
            if size <= 0:
                window.clear()
                continue
            return read_exact(uart, size)


def scan_uart(args: argparse.Namespace) -> int:
    end_at = time.monotonic() + args.scan_seconds
    window = bytearray()
    bytes_seen = 0
    records = 0
    nal_counts: Counter[int] = Counter()
    last_error = ""

    with serial.Serial(args.port, args.baud, timeout=0.005) as uart:
        print(f"scanning {args.port} @ {args.baud} for {args.scan_seconds}s", file=sys.stderr)
        while time.monotonic() < end_at:
            chunk = uart.read(uart.in_waiting or 1)
            if not chunk:
                continue
            bytes_seen += len(chunk)
            window.extend(chunk)

            while True:
                marker_pos = -1
                marker = b""
                for magic in MAGICS:
                    pos = window.find(magic)
                    if pos >= 0 and (marker_pos < 0 or pos < marker_pos):
                        marker_pos = pos
                        marker = magic
                if marker_pos < 0:
                    if len(window) > 8:
                        del window[:-8]
                    break
                if marker_pos > 0:
                    del window[:marker_pos]
                if len(window) < len(marker) + 4:
                    break
                size = decode_record_size(window[len(marker):len(marker) + 4])
                if size <= 0:
                    del window[0]
                    last_error = "bad size"
                    continue
                need = len(marker) + 4 + size
                if len(window) < need:
                    break
                payload = bytes(window[len(marker) + 4:need])
                del window[:need]
                records += 1
                nal = h264_nal_type(payload)
                if nal is not None:
                    nal_counts[nal] += 1

    print(f"bytes={bytes_seen} records={records} nal_types={dict(nal_counts)} last_error={last_error}")
    return 0


def open_output(path: str | None, stdout: bool):
    if stdout:
        if os.name == "nt":
            import msvcrt

            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        return sys.stdout.buffer
    if path:
        return open(path, "wb")
    return open("stream.h264", "wb")


def h264_nal_type(payload: bytes) -> int | None:
    for start_code in START_CODES:
        if payload.startswith(start_code) and len(payload) > len(start_code):
            return payload[len(start_code)] & 0x1F
    if payload:
        return payload[0] & 0x1F
    return None


def write_annexb(out, payload: bytes) -> int:
    if payload.startswith(START_CODES):
        out.write(payload)
        return len(payload)
    out.write(b"\x00\x00\x00\x01")
    out.write(payload)
    return len(payload) + 4


def find_annexb_sync(data: bytes) -> int:
    for start_code in START_CODES:
        pos = data.find(start_code)
        while pos >= 0:
            nal_pos = pos + len(start_code)
            if nal_pos < len(data) and (data[nal_pos] & 0x1F) in ANNEXB_SYNC_NALS:
                return pos
            pos = data.find(start_code, pos + 1)
    return -1


def reset_stream_devices(args: argparse.Namespace, uart: serial.Serial) -> None:
    uart.reset_input_buffer()
    if args.reset_nrf:
        subprocess.run(
            [
                r"C:\ncs\toolchains\936afb6332\nrfutil\bin\nrfutil.exe",
                "device",
                "reset",
                "--serial-number",
                args.reset_nrf,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        time.sleep(0.5)
        uart.reset_input_buffer()
    if args.reset_esp:
        with serial.Serial(args.reset_esp, 115200, timeout=0.05) as esp:
            esp.dtr = False
            esp.rts = False
            time.sleep(0.2)
            esp.rts = True
            time.sleep(0.2)
            esp.rts = False
        time.sleep(0.5)
        uart.reset_input_buffer()


def receive_annexb(args: argparse.Namespace) -> int:
    with serial.Serial(args.port, args.baud, timeout=0.005) as uart:
        print(f"searching raw Annex-B H.264 on {args.port} @ {args.baud}", file=sys.stderr)
        reset_stream_devices(args, uart)
        synced = False
        window = bytearray()
        bytes_out = 0
        started_at = time.monotonic()
        with open_output(args.output, args.stdout) as out:
            while True:
                if args.seconds > 0 and time.monotonic() - started_at >= args.seconds:
                    break
                chunk = uart.read(uart.in_waiting or 1)
                if not chunk:
                    continue
                if not synced:
                    window.extend(chunk)
                    sync_pos = find_annexb_sync(bytes(window))
                    if sync_pos < 0:
                        if len(window) > 32:
                            del window[:-32]
                        continue
                    chunk = bytes(window[sync_pos:])
                    window.clear()
                    synced = True
                    print("raw stream started", file=sys.stderr)

                out.write(chunk)
                out.flush()
                bytes_out += len(chunk)
                if args.report_every > 0 and bytes_out // 65536 != (bytes_out - len(chunk)) // 65536:
                    elapsed = max(time.monotonic() - started_at, 0.001)
                    kbps = (bytes_out * 8) / elapsed / 1000
                    print(f"bytes={bytes_out} rate={kbps:.0f} kbps", file=sys.stderr)


def receive(args: argparse.Namespace) -> int:
    with serial.Serial(args.port, args.baud, timeout=0.1) as uart:
        reset_stream_devices(args, uart)
        if args.reset:
            uart.dtr = False
            uart.rts = True
            time.sleep(0.1)
            uart.dtr = True
            uart.rts = False
            time.sleep(0.3)
        print(f"searching H.264 records on {args.port} @ {args.baud}", file=sys.stderr)

        frames = 0
        bytes_out = 0
        synced = args.no_sync
        sps: bytes | None = None
        pps: bytes | None = None
        started_at = time.monotonic()
        deadline = started_at + args.seconds if args.seconds > 0 else None
        with open_output(args.output, args.stdout) as out:
            while args.frames <= 0 or frames < args.frames:
                payload = read_record(uart, deadline)
                if payload is None:
                    break
                nal_type = h264_nal_type(payload)
                if nal_type == 7:
                    sps = payload
                    if not args.no_sync:
                        continue
                elif nal_type == 8:
                    pps = payload
                    if not args.no_sync:
                        continue

                chunks = [payload]
                if not args.no_sync and not synced:
                    if nal_type != 5 or sps is None or pps is None:
                        continue
                    chunks = [sps, pps, payload]
                    synced = True
                    print("stream started", file=sys.stderr)
                elif not args.no_sync and nal_type == 5:
                    chunks = []
                    if sps is not None:
                        chunks.append(sps)
                    if pps is not None:
                        chunks.append(pps)
                    chunks.append(payload)

                for chunk in chunks:
                    bytes_out += write_annexb(out, chunk)
                out.flush()
                frames += len(chunks)
                if frames % args.report_every == 0:
                    elapsed = max(time.monotonic() - started_at, 0.001)
                    kbps = (bytes_out * 8) / elapsed / 1000
                    print(f"records={frames} bytes={bytes_out} rate={kbps:.0f} kbps", file=sys.stderr)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--frames", type=int, default=0, help="0 means unlimited")
    parser.add_argument("--output", default="stream.h264")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--report-every", type=int, default=20)
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--no-sync", action="store_true", help="write records immediately, even before SPS/PPS/IDR")
    parser.add_argument("--scan", action="store_true", help="scan UART and print raw record/NAL counters")
    parser.add_argument("--scan-seconds", type=int, default=10)
    parser.add_argument("--annexb", action="store_true", help="receive raw Annex-B H.264 bytes instead of H4F1 records")
    parser.add_argument("--seconds", type=float, default=0.0, help="capture duration; 0 means unlimited")
    parser.add_argument("--reset-esp", help="ESP32 serial port to reset after opening receiver UART")
    parser.add_argument("--reset-nrf", help="nRF J-Link serial number to reset after opening receiver UART")
    args = parser.parse_args()
    if args.list_ports:
        return args
    if not args.port:
        parser.error("port required unless --list-ports is used")
    return args


def main() -> int:
    args = parse_args()
    if args.list_ports:
        return list_serial_ports()
    if args.scan:
        return scan_uart(args)
    if args.annexb:
        return receive_annexb(args)
    return receive(args)


if __name__ == "__main__":
    raise SystemExit(main())
