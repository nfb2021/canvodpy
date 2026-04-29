---
title: Conventions and Defaults
description: Default conventions and processing defaults used by canVODpy
---

# Conventions and Defaults

This page documents the default conventions and processing choices built into
canVODpy. These defaults ensure consistent, reproducible results across sites
and receivers. All defaults can be overridden via configuration.

---

## 1. File Naming Convention

The canVOD file naming convention provides a unique, self-describing
filename for every GNSS observation file across all sites, receivers,
agencies, and formats. It is designed to be compatible with the
[RINEX v3.04 long-name convention](https://files.igs.org/pub/data/format/rinex304.pdf)
while extending it with fields specific to GNSS-Transmissometry.

### Format

```
{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]
```


<iframe src="../diagrams/naming-convention-embed.html" style="width:100%;height:320px;border:none;display:block;margin:1.5rem 0;" loading="lazy"></iframe>

### Fields

| Field | Width | Description | Example |
|-------|-------|-------------|---------|
| `SIT` | 3 | Site ID, uppercase | `ROS`, `HAI`, `FON`, `LBS` |
| `T` | 1 | Receiver type: **R** = reference, **A** = active (below-canopy) | `R`, `A` |
| `NN` | 2 | Receiver number, zero-padded (01–99) | `01`, `35` |
| `AGC` | 3 | Data provider / agency ID, uppercase | `TUW`, `GFZ`, `MPI` |
| `_R` | 2 | Literal — **R** for Receiver | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001–366) | `001`, `222` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000`, `1530` |
| `PERIOD` | 3 | Batch size: 2-digit value + unit (S/M/H/D) | `01D`, `15M`, `01H` |
| `SAMPLING` | 3 | Data frequency: 2-digit value + unit (S/M/H/D) | `01S`, `05S`, `05M` |
| `CONTENT` | 2 | User-defined content code, default `AA` | `AA` |
| `TYPE` | 2–4 | File format, lowercase | `rnx`, `sbf`, `ubx`, `nmea` |
| `COMPRESSION` | — | Optional compression extension | `zip`, `gz`, `bz2`, `zst` |

### Duration codes

The `PERIOD` and `SAMPLING` fields use a 2-digit value followed by a unit
character:

| Unit | Meaning | Example |
|------|---------|---------|
| `S` | Seconds | `05S` = 5 seconds |
| `M` | Minutes | `15M` = 15 minutes |
| `H` | Hours | `01H` = 1 hour |
| `D` | Days | `01D` = 1 day |

### Receiver types

| Code | Role | Description |
|------|------|-------------|
| `R` | Reference | Above canopy — unobstructed sky view |
| `A` | Active | Below canopy — signal attenuated by vegetation |

### Examples

**Daily merged, 5-second sampling (reference):**

```
ROSR01TUW_R_20250010000_01D_05S_AA.rnx
│  │ │ │     │       │    │   │   │  └── RINEX observation
│  │ │ │     │       │    │   │   └── content: default
│  │ │ │     │       │    │   └── sampling: 5 seconds
│  │ │ │     │       │    └── period: 1 day
│  │ │ │     │       └── start: 00:00
│  │ │ │     └── 2025, DOY 001
│  │ │ └── agency: TU Wien
│  │ └── receiver number 01
│  └── R = reference
└── site: Rosalia
```

**Daily merged, 5-second sampling (active / below-canopy):**

```
ROSA01TUW_R_20250010000_01D_05S_AA.rnx
   ^
   A = active (below-canopy)
```

**15-minute sub-daily file, SBF format:**

```
ROSR35TUW_R_20232221530_15M_05S_AA.sbf
      ^^                 ^^^        ^^^
      receiver #35       15-min     Septentrio Binary Format
```

**Compressed daily file, 1-second sampling:**

```
HAIA01GFZ_R_20250010000_01D_01S_AA.rnx.zip
^^^                                    ^^^^
Hainich                                zip compressed
```


### SP3 and CLK files

SP3 orbit and CLK clock product files already follow the
IGS long-name convention and **do not** need renaming under this scheme.



*Questions or suggestions? Open a discussion on
[GitHub](https://github.com/nfb2021/canvodpy/discussions).*

---

**Next in the trail:** [API Levels](guides/api-levels.md) · [Getting Started](guides/getting-started.md) · [Architecture](architecture.md) · [AI Development](guides/ai-development.md)
