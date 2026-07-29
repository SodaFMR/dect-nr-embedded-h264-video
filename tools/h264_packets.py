"""H264D packet helpers for the ESP32-P4/nRF9151 video path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


MAGIC = b"\xA5\x5A"
VERSION = 1
PACKET_SIZE = 700
HEADER_SIZE = 8
PAYLOAD_SIZE = PACKET_SIZE - HEADER_SIZE
PADDING_BYTE = 0xFF


class PacketType(IntEnum):
    IDLE = 0x00
    NAL_SINGLE = 0x01
    NAL_FIRST = 0x02
    NAL_CONT = 0x03
    NAL_LAST = 0x04
    SPS = 0x10
    PPS = 0x11


@dataclass(frozen=True)
class Packet:
    packet_type: PacketType
    sequence: int
    payload: bytes


def pack_packet(packet_type: PacketType, sequence: int, payload: bytes) -> bytes:
    if len(payload) > PAYLOAD_SIZE:
        raise ValueError(f"payload too large: {len(payload)} > {PAYLOAD_SIZE}")
    if not 0 <= sequence <= 0xFFFF:
        raise ValueError("sequence must fit in uint16")

    header = bytearray()
    header.extend(MAGIC)
    header.append(VERSION)
    header.append(int(packet_type))
    header.extend(sequence.to_bytes(2, "little"))
    header.extend(len(payload).to_bytes(2, "little"))

    padding = bytes([PADDING_BYTE]) * (PACKET_SIZE - HEADER_SIZE - len(payload))
    return bytes(header) + payload + padding


def packetize_nal(
    nal: bytes,
    *,
    sequence: int = 0,
    single_type: PacketType = PacketType.NAL_SINGLE,
) -> Iterable[bytes]:
    if single_type in {PacketType.NAL_FIRST, PacketType.NAL_CONT, PacketType.NAL_LAST}:
        raise ValueError("single_type must describe a complete NAL kind")

    if len(nal) <= PAYLOAD_SIZE:
        yield pack_packet(single_type, sequence & 0xFFFF, nal)
        return

    chunks = [nal[i : i + PAYLOAD_SIZE] for i in range(0, len(nal), PAYLOAD_SIZE)]
    for index, chunk in enumerate(chunks):
        if index == 0:
            packet_type = PacketType.NAL_FIRST
        elif index == len(chunks) - 1:
            packet_type = PacketType.NAL_LAST
        else:
            packet_type = PacketType.NAL_CONT
        yield pack_packet(packet_type, (sequence + index) & 0xFFFF, chunk)


def parse_packet(packet: bytes) -> Packet:
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"packet must be exactly {PACKET_SIZE} bytes")
    if packet[:2] != MAGIC:
        raise ValueError("bad packet magic")
    if packet[2] != VERSION:
        raise ValueError(f"unsupported packet version: {packet[2]}")

    packet_type = PacketType(packet[3])
    sequence = int.from_bytes(packet[4:6], "little")
    payload_length = int.from_bytes(packet[6:8], "little")
    if payload_length > PAYLOAD_SIZE:
        raise ValueError(f"payload length too large: {payload_length}")

    return Packet(packet_type, sequence, packet[HEADER_SIZE : HEADER_SIZE + payload_length])


def parse_stream(data: bytes) -> Iterable[Packet]:
    offset = 0
    while offset < len(data):
        marker = data.find(MAGIC, offset)
        if marker < 0:
            return
        if len(data) - marker < PACKET_SIZE:
            return

        candidate = data[marker : marker + PACKET_SIZE]
        try:
            yield parse_packet(candidate)
            offset = marker + PACKET_SIZE
        except ValueError:
            offset = marker + 1
