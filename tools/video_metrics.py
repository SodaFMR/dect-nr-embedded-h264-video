"""Analysis helpers for repeatable DECT video measurements."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import statistics


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[max(0, min(index, len(ordered) - 1))]


def detect_luma_transitions(
    samples: Sequence[tuple[float, float]],
    min_stable_frames: int = 2,
) -> tuple[float, list[tuple[float, int]]]:
    if not samples:
        return 0.0, []

    lumas = [sample[1] for sample in samples]
    threshold = (percentile(lumas, 0.10) + percentile(lumas, 0.90)) / 2.0
    states = [1 if luma >= threshold else 0 for _, luma in samples]
    stable_state = states[0]
    candidate_state: int | None = None
    candidate_start = 0
    candidate_count = 0
    transitions: list[tuple[float, int]] = []

    for index, state in enumerate(states[1:], start=1):
        if state == stable_state:
            candidate_state = None
            candidate_count = 0
            continue

        if state != candidate_state:
            candidate_state = state
            candidate_start = index
            candidate_count = 1
        else:
            candidate_count += 1

        if candidate_count >= min_stable_frames:
            transitions.append((samples[candidate_start][0], state))
            stable_state = state
            candidate_state = None
            candidate_count = 0

    return threshold, transitions


def match_transition_latencies(
    source: Sequence[tuple[float, int]],
    observed: Sequence[tuple[float, int]],
    max_latency_s: float = 2.0,
) -> list[dict[str, float | int]]:
    matches: list[dict[str, float | int]] = []
    observed_index = 0

    for source_time, source_state in source:
        while observed_index < len(observed):
            observed_time, observed_state = observed[observed_index]
            if observed_time < source_time or observed_state != source_state:
                observed_index += 1
                continue
            latency = observed_time - source_time
            if latency <= max_latency_s:
                matches.append(
                    {
                        "source_time_s": source_time,
                        "observed_time_s": observed_time,
                        "state": source_state,
                        "latency_ms": latency * 1000.0,
                    }
                )
                observed_index += 1
            break

    return matches


def best_transition_matches(
    source: Sequence[tuple[float, int]],
    observed: Sequence[tuple[float, int]],
    max_latency_s: float = 2.0,
) -> tuple[str, list[dict[str, float | int]]]:
    direct = match_transition_latencies(source, observed, max_latency_s)
    inverted_observed = [(timestamp, state ^ 1) for timestamp, state in observed]
    inverted = match_transition_latencies(source, inverted_observed, max_latency_s)
    if len(inverted) > len(direct):
        return "inverted", inverted
    return "direct", direct


def horizontal_contrast(frame: bytes, width: int, height: int) -> float:
    if width < 2 or height < 1 or len(frame) != width * height:
        raise ValueError("frame dimensions do not match grayscale payload")
    quarter = max(1, width // 4)
    left_sum = 0
    right_sum = 0
    for row in range(height):
        start = row * width
        left_sum += sum(frame[start : start + quarter])
        right_sum += sum(frame[start + width - quarter : start + width])
    samples = quarter * height
    return (left_sum - right_sum) / samples


def summarize_stream_records(
    records: Sequence[tuple[float, int, int]],
) -> dict[str, object]:
    if not records:
        return {
            "records": 0,
            "received_bytes": 0,
            "nal_counts": {},
            "video_frames": 0,
            "measurement_duration_s": 0.0,
            "received_fps": 0.0,
            "bitrate_kbps": 0.0,
            "frame_interval_ms_mean": 0.0,
            "frame_interval_ms_stdev": 0.0,
            "frame_interval_ms_p50": 0.0,
            "frame_interval_ms_p95": 0.0,
            "frame_interval_ms_p99": 0.0,
            "frame_interval_ms_max": 0.0,
            "frame_gaps_over_200ms": 0,
            "frame_gaps_over_500ms": 0,
        }

    first_time = records[0][0]
    last_time = records[-1][0]
    duration = max(0.0, last_time - first_time)
    frame_times = [timestamp for timestamp, nal_type, _ in records if nal_type in (1, 5)]
    intervals_ms = [
        (right - left) * 1000.0
        for left, right in zip(frame_times, frame_times[1:])
    ]
    frame_duration = frame_times[-1] - frame_times[0] if len(frame_times) > 1 else 0.0
    received_bytes = sum(size for _, _, size in records)
    nal_counts = Counter(str(nal_type) for _, nal_type, _ in records)

    return {
        "records": len(records),
        "received_bytes": received_bytes,
        "nal_counts": dict(sorted(nal_counts.items())),
        "video_frames": len(frame_times),
        "measurement_duration_s": round(duration, 3),
        "received_fps": round((len(frame_times) - 1) / frame_duration, 3)
        if frame_duration > 0
        else 0.0,
        "bitrate_kbps": round(received_bytes * 8 / duration / 1000.0, 3)
        if duration > 0
        else 0.0,
        "frame_interval_ms_mean": round(statistics.mean(intervals_ms), 3)
        if intervals_ms
        else 0.0,
        "frame_interval_ms_stdev": round(statistics.pstdev(intervals_ms), 3)
        if intervals_ms
        else 0.0,
        "frame_interval_ms_p50": round(percentile(intervals_ms, 0.50), 3),
        "frame_interval_ms_p95": round(percentile(intervals_ms, 0.95), 3),
        "frame_interval_ms_p99": round(percentile(intervals_ms, 0.99), 3),
        "frame_interval_ms_max": round(max(intervals_ms), 3) if intervals_ms else 0.0,
        "frame_gaps_over_200ms": sum(interval > 200.0 for interval in intervals_ms),
        "frame_gaps_over_500ms": sum(interval > 500.0 for interval in intervals_ms),
    }
