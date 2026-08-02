# Experimental Metrics for the Video System

Measurement date: 12 June 2026.

This document records the first reproducible measurements of the complete
H.264-over-DECT NR+ video chain. The results were obtained with the camera and
video receiver intended for the ground vehicle. The implementation is shared by
the ground-vehicle and drone variants; consequently, the results are
representative of the architecture. They should not be assumed to be identical
for every hardware pair, separation, antenna orientation, or radio environment.

## 1. Measured Chain

```text
OV2710 -> MIPI-CSI -> ESP32-P4 -> H.264 hardware
       -> SPI -> Nordic TX -> DECT NR+
       -> Nordic RX -> UART 921600 -> PC -> FFmpeg
```

Equipment available during the experiment:

- ESP32-P4-EYE, connected through the test computer's camera USB port.
- Nordic receiver, connected through a J-Link CDC UART.
- Nordic transmitter, externally powered and connected to the ESP32-P4 through SPI.
- Camera aimed at the main monitor of the test bench.
- Carrier assigned to the ground-vehicle video link: `1670`.

The exact transmitter--receiver separation was not recorded. These measurements
cannot be used to derive range, sensitivity, or distance-dependent degradation.

## 2. Implementation Configuration

### 2.1. Capture and Encoding

The ESP32-P4 firmware configuration is:

| Parameter | Value |
|---|---:|
| Sensor | OV2710 |
| Capture | 1280 x 720, RAW10, 25 FPS |
| Encoded resolution | 1008 x 576 |
| Encoder input format | YUV422 |
| Encoder | Hardware H.264 |
| Observed profile | Constrained Baseline |
| Target frame rate | 10 FPS |
| Target bitrate | 200 kbit/s |
| GOP | 3 pictures |
| QP | 30 to 44 |

The configured bitrate is a rate-control target, not a hard limit. A scene with
substantial detail or motion can temporarily produce a higher data rate.

### 2.2. SPI and DECT NR+ Transport

Each H264D SPI fragment is 64 bytes long:

- H264D header: 10 bytes.
- H.264 payload: 54 bytes.
- Useful payload efficiency per SPI fragment: `54 / 64 = 84.375 %`.
- Protection: sequence number and CRC-16 per fragment.
- Configured SPI clock: 8 MHz.
- Flow control: `READY` signal.

The transmitter aggregates up to 10 SPI fragments into each DECT PDU:

- DECT aggregation header: 8 bytes.
- Ten H264D fragments: 640 bytes.
- Typical maximum aggregation size: 648 bytes.
- Useful H.264 video in a complete aggregation: 540 bytes.
- Available transport-block size with MCS 4: up to 700 bytes.
- H.264 efficiency relative to the 700-byte block: `540 / 700 = 77.143 %`.
- Maximum time before an incomplete aggregation is forced: 10 ms.
- Configured minimum interval between TX operations: 2.1 ms.
- TX queue: 128 aggregations.
- RX queue: 64 aggregations.

The receiver output uses a 921600-baud UART. With 8N1 framing, each byte
consumes 10 physical bits and the theoretical useful rate is:

```text
921600 / 10 = 92160 bytes/s = 737.28 kbit/s
```

The 200-kbit/s encoder target remains below this limit.

## 3. Methodology

The following purpose-built tools are provided in `tools/`:

- `video_stream_metrics.py`: captures NAL units, timestamps their arrival,
  generates Annex-B, runs `ffprobe`, and validates complete decoding with FFmpeg.
- `video_latency_test.py`: presents a high-contrast pattern on the monitor and
  measures when it appears in the decoded video.
- `video_motion_pattern.py`: generates repeatable visual motion to stress the
  encoder and link.
- `video_metrics.py`: calculates percentiles, intervals, data rate, and
  timestamp matching.

The latency pattern divides the screen into one white and one black half and
alternates their positions. The horizontal contrast of each decoded picture is
used:

```text
C = mean(Y_left) - mean(Y_right)
```

This method prevents camera auto-exposure from neutralising a full-screen
white/black alternation. The minimum monitor-synchronisation uncertainty at
60 Hz is approximately 16.67 ms.

## 4. Throughput, Frame Rate, and Regularity

### 4.1. Static Scene, 60 Seconds

| Metric | Result |
|---|---:|
| Observed duration | 59.968 s |
| Received H.264 bytes | 1,240,822 bytes |
| NAL records | 1,492 |
| Received H.264 pictures | 490 |
| Decoded pictures | 489 |
| Effective frame rate | 8.154 FPS |
| Mean bitrate | 165.531 kbit/s |
| Mean interval | 122.634 ms |
| Interval standard deviation | 97.874 ms |
| Interval 50th percentile | 109 ms |
| Interval 95th percentile | 266 ms |
| Interval 99th percentile | 266 ms |
| Maximum interval | 313 ms |
| Gaps longer than 200 ms | 167 |
| Gaps longer than 500 ms | 0 |
| Pictures reported as corrupt | 6 of 489, 1.227 % |

Picture-unit size:

| Type | Mean | P50 | P95 | Maximum |
|---|---:|---:|---:|---:|
| P | 288 bytes | 310 bytes | 507 bytes | 1,525 bytes |
| IDR | 6,828 bytes | 6,166 bytes | 8,134 bytes | 10,383 bytes |

The static scene produces small P pictures. IDR pictures are much larger and
require more serialisation time. The 167 intervals above 200 ms coincide almost
exactly with the 167 observed IDR pictures. The irregularity is associated with
the GOP and data bursts, rather than complete disconnections.

### 4.2. Intensive Motion, 60 Seconds

| Metric | Result |
|---|---:|
| Observed duration | 59.781 s |
| Received H.264 bytes | 2,185,655 bytes |
| Received H.264 pictures | 471 |
| Decoded pictures | 466 |
| Effective frame rate | 7.862 FPS |
| Mean bitrate | 292.488 kbit/s |
| Mean interval | 127.194 ms |
| Interval standard deviation | 44.294 ms |
| P50 / P95 / P99 | 125 / 188 / 219 ms |
| Maximum interval | 234 ms |
| Gaps longer than 200 ms | 18 |
| Gaps longer than 500 ms | 0 |
| Pictures reported as corrupt | 17 of 466, 3.648 % |

Picture-unit size:

| Type | Mean | P50 | P95 | Maximum |
|---|---:|---:|---:|---:|
| P | 4,363.6 bytes | 4,261 bytes | 6,311 bytes | 6,514 bytes |
| IDR | 5,118.6 bytes | 5,115 bytes | 5,364 bytes | 5,413 bytes |

Compared with the static scene, the bitrate increases by 76.7 %. Motion reduces
the efficiency of temporal prediction, so P pictures are no longer small and
approach the size of IDR pictures.

### 4.3. Motion Stability, 180 Seconds

| Metric | Result |
|---|---:|
| Observed duration | 179.891 s |
| Received H.264 bytes | 5,880,472 bytes |
| Received H.264 pictures | 1,461 |
| Decoded pictures | 1,452 |
| Effective frame rate | 8.116 FPS |
| Mean bitrate | 261.513 kbit/s |
| Mean interval | 123.213 ms |
| Interval standard deviation | 36.547 ms |
| P50 / P95 / P99 | 125 / 172 / 203 ms |
| Maximum interval | 359 ms |
| Gaps longer than 200 ms | 25 |
| Gaps longer than 500 ms | 0 |
| Pictures reported as corrupt | 30 of 1,452, 2.066 % |

There were no half-second interruptions or complete stream losses during the
three-minute experiment. Throughput and effective frame rate remained stable.

## 5. End-to-End Latency

The measurement includes:

```text
monitor update
-> OV2710 exposure and readout
-> ISP and H.264 encoding
-> SPI fragmentation
-> DECT NR+ transmission
-> reconstruction and UART
-> FFmpeg decoding
```

Two independent series of 30 transitions were performed:

| Series | Detected | Mean | Standard deviation | Median | P95 | Maximum |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 30/30 | 464.433 ms | 48.376 ms | 453 ms | 531 ms | 609 ms |
| 2 | 30/30 | 498.400 ms | 102.223 ms | 476.5 ms | 750 ms | 953 ms |
| Combined | 60/60 | 481.417 ms | 81.752 ms | 469 ms | 531 ms | 953 ms |

This is monitor-to-decoder latency, not radio latency alone. It includes up to
one capture period, encoding, aggregation wait, transmission, UART output, and
software presentation.

## 6. Full-Reference PSNR-Y Reported in the Manuscript

The manuscript reports luminance PSNR (PSNR-Y) for the three controlled
workloads. The stated procedure compares a source-side reference sequence
with the corresponding receiver-side H.264 reconstruction after host-side
decoding. Both sequences are represented at 1008 x 576 pixels; the comparison
uses the 8-bit luminance component and only successfully decoded matched
pictures.

| Workload | Matched decoded pictures | Mean PSNR-Y |
|---|---:|---:|
| Static, 60 s | 489 | 38.5 dB |
| Motion, 60 s | 466 | 31.0 dB |
| Motion, 180 s | 1,452 | 32.5 dB |

For each matched picture, the reported calculation is:

```text
MSE_Y = mean((Y_reference - Y_received)^2)
PSNR-Y = 10 log10(255^2 / MSE_Y)
```

### Availability limitation

The source reference frames and the decoded frame sequences used for this
PSNR calculation are not available in this repository. Consequently, the
PSNR-Y values above document the values reported in the manuscript, but they
cannot be independently recomputed from the public artifacts currently
provided here. The repository also does not include a PSNR-specific frame
matching script.

## 7. Achieved Compression

One 1008 x 576 YUV422 picture contains:

```text
1008 x 576 x 2 = 1,161,216 bytes = 1.161 MB
```

At 10 FPS, the uncompressed stream would require:

```text
1,161,216 x 10 x 8 = 92.897 Mbit/s
```

Comparison with the measured H.264 bitrate:

| Scenario | Measured H.264 | Reduction relative to YUV422 |
|---|---:|---:|
| Static | 165.531 kbit/s | 561.2:1 |
| Motion, 60 s | 292.488 kbit/s | 317.6:1 |
| Motion, 180 s | 261.513 kbit/s | 355.2:1 |

This reduction explains why H.264 video is viable and uncompressed YUV422
transmission is not.

## 8. Losses and Measurement Limitations

The configured GOP contains one IDR picture and two P pictures. Considering
only complete GOPs, the inferred absence of P pictures was:

| Scenario | Expected P pictures | Observed P pictures | Missing | Inferred rate |
|---|---:|---:|---:|---:|
| Static | 332 | 323 | 9 | 1.804 % |
| Motion, 60 s | 324 | 308 | 16 | 3.285 % |
| Motion, 180 s | 984 | 968 | 16 | 1.083 % |

This is an inference based on the GOP structure, not a direct PHY counter. The
beginning and end of a capture can introduce a difference of up to two pictures.
The corruption rates reported by FFmpeg are an independent, direct observation
of the reconstructed stream.

The following were not measured:

- Link RSSI, SNR, or BLER.
- Maximum range.
- The effect of controlled interference.
- Energy consumption.
- Control-channel latency.

## 9. Experimental Conclusions

1. The complete chain maintains 1008 x 576 H.264 video for at least three
   minutes without interruptions longer than 500 ms.
2. The received frame rate remains around 8 FPS, compared with the 10-FPS
   target.
3. The measured end-to-end latency is approximately 481 ms on average.
4. Motion increases bitrate and reported corruption because it reduces
   inter-picture prediction efficiency.
5. The short GOP improves recovery after loss, but produces frequent IDR
   pictures and serialisation bursts.
6. H.264 reduces the data rate by between 318:1 and 561:1 relative to
   uncompressed YUV422.
7. The results can serve as a reference for other boards running the same
   firmware, but must be repeated before quantitative equivalence is claimed.

## 10. Artifacts

Structured results:

```text
metrics/car_static_run1/
metrics/car_dynamic_run1/
metrics/car_dynamic_long_run1/
metrics/car_latency_run1/
metrics/car_latency_run2/
```

Each experiment retains, where applicable:

- `summary.json`: numerical summary.
- `records.csv`: timestamp, NAL type, and size.
- `source_transitions.csv`: changes presented on the monitor.
- `decoded_contrast.csv`: contrast measured in each decoded picture.
- `observed_transitions.csv`: detected changes.
- `latency_matches.csv`: matching and latency.
