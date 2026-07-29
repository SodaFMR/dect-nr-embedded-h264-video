# Embedded H.264 Video over DECT NR+

This repository is the public measurement companion for the paper
**A Compact Embedded H.264-over-DECT NR+ System for Mobile Teleoperation**.
It contains only the recorded metrics and the host-side measurement/analysis
scripts used for the reported experiments. Embedded firmware, binary images,
and the separate vehicle-control software are intentionally not included.

The measurements cover the complete capture-to-decoder video path: an
ESP32-P4-EYE camera produces hardware-encoded H.264, an nRF9151-based DECT
NR+ link transports the stream, and the receiver forwards reconstructed video
to a host through UART for standard H.264 decoding.

## Repository contents

```text
tools/                         Measurement and analysis scripts
metrics/                       Raw CSV measurements and JSON summaries
METRICS.md                     Description of the recorded datasets
CITATION.cff                   Citation metadata
```

The datasets contain three sustained video workloads:

- static scene for 60 s;
- repeatable dynamic stimulus for 60 s;
- the same dynamic stimulus for 180 s.

The latency measurements contain two independent 30-transition runs and
their combined 60-transition analysis. Raw files are retained so that the
reported aggregate values can be checked independently.

## Tested video profile

| Parameter | Configuration |
|---|---|
| Camera | OV2710 through ESP32-P4-EYE MIPI CSI |
| Encoded stream | H.264/AVC, 1008 x 576 |
| Target frame rate | 10 frames/s |
| Target bitrate | 200 kbit/s |
| GOP | 3 pictures |
| QP range | 30--44 |
| SPI record | 64 bytes, 54-byte payload |
| DECT NR+ video carrier | 1670 (ground vehicle), 1671 (drone) |
| Receiver output | UART, 921600 baud, 8N1 |

## Requirements

The host-side tools require Python 3.10 or newer, `pyserial`, and FFmpeg
(`ffmpeg` and `ffprobe`). The graphical stimulus and latency tools also
require a working Tk runtime. Install Python dependencies with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Debian or Ubuntu, install Tk with `sudo apt install python3-tk` if it is
not already present.

## Reproducing the measurements and analysis

The existing results can be inspected directly in `metrics/`. The scripts
used to collect or analyse them are in `tools/`:

- `video_stream_metrics.py` collects received-stream and decoder metrics;
- `video_latency_test.py` measures monitor-to-decoder transition latency;
- `video_motion_pattern.py` generates the repeatable dynamic stimulus;
- `video_metrics.py` computes interval, bitrate, and transition statistics;
- `h264_usb_receiver.py` reads the framed H.264 records from the receiver;
- `h264_packets.py` implements the fixed-size H.264 transport records used by
  the host-side transport parser.

Live capture commands require the demonstrator hardware, a suitable serial
port, and the corresponding embedded firmware; those firmware artifacts are
outside the scope of this public measurement repository.

## Scope and limitations

The included measurements were obtained with a fixed direct-link indoor
configuration, with the mobile-platform demonstrations reported separately
in the paper. They demonstrate end-to-end video operation and quantify the
embedded transport under the reported workloads; they do not establish DECT
NR+ radio range, coverage, physical-layer reliability, energy consumption, or
high-speed teleoperation suitability.

## Citation

If you use these data or scripts, please cite the associated article:

```text
José David Guerrero Romero, Antonio Javier García Sánchez, Joan García Haro,
Juan Carlos Jacobo Aarnoutse Sánchez, and Julián Murillo Portocarrero,
"A Compact Embedded H.264-over-DECT NR+ System for Mobile Teleoperation."
```
