# Vendor datasheets — the primary sources

Manufacturer documents for the parts on this car's data platform. **These are the authority for
register maps, reset values, tolerances and conversion formulas.** A figure recalled from memory
is not a source; if it is not in a document here (or another primary source), label it
*recalled* until it is checked. (Spool charter, standing obligation 7 — CIO, 2026-09-22.)

Enclosure/mechanical documents live with their enclosure under `hardware/enclosures/*/datasheets/`.
This folder is for the **electrical / register** documents that code and specs rest on.

## Index

| Part | Document | Rev | Retrieved | Source | SHA-256 |
|---|---|---|---|---|---|
| TDK InvenSense **ICM-20948** 9-DoF IMU | [`icm-20948/DS-000189-ICM-20948-v1.3.pdf`](icm-20948/DS-000189-ICM-20948-v1.3.pdf) | 1.3 | 2026-09-22 | `https://cdn.sparkfun.com/assets/7/f/e/c/d/DS-000189-ICM-20948-v1.3.pdf` (SparkFun mirror of the revision Adafruit's own link `adafru.it/MC5` resolves to) | `5a6c1b7b71633986bec05439335844a91769e46f9d90c2602d0f7c1a559ae016` |
| Analog Devices (Maxim) **MAX17048** fuel gauge | **MISSING — human task** | — | — | `https://www.analog.com/media/en/technical-documentation/data-sheets/max17048-max17049.pdf` — the host resets automated requests | — |
| Geekworm **X1209** UPS HAT | **MISSING — human task** (vendor wiki page, save as PDF) | — | — | `https://wiki.geekworm.com/X1209` — returns 403 to automated requests | — |

## Traps found while sourcing these — read before trusting a link

- 🔴 **Adafruit's ICM-20948 guide links its datasheet as `adafru.it/Iqf`, which redirects to an ST
  `LSM6DS33` datasheet — a different part.** Its second link, `adafru.it/MC5`, reaches the real
  DS-000189 v1.3 via a TDK download page. **Check the part number on page 1 of any datasheet you
  pull, not the link text.**
- ⚠️ **The same Adafruit guide contradicts itself on the gyro unit** — prose says degrees/sec, its
  example prints rad/s. **The driver source (`adafruit_icm20x`, `_ICM20X_RAD_PER_DEG`) and this
  datasheet are the authority: the driver returns rad/s.**
- ⚠️ **TDK's own download page is JavaScript-rendered**; the PDF URL is not in the HTML. The
  SparkFun CDN copy is the same revision.

## Facts verified against DS-000189 rev 1.3 (2026-09-22)

| Fact | Datasheet | Page / section |
|---|---|---|
| `WHO_AM_I` reset value | `0xEA` | §8.1 |
| Temperature | `TEMP_degC = ((TEMP_OUT − RoomTemp_Offset) / 333.87) + 21` | §3, §8.30–8.31 |
| `GYRO_CONFIG_1` reset (bank 2, 0x01) | `0x01` ⇒ DLPF **enabled**, `GYRO_DLPFCFG = 0` | §10.2 |
| `ACCEL_CONFIG` reset (bank 2, 0x14) | `0x01` ⇒ DLPF **enabled**, `ACCEL_DLPFCFG = 0` | §10.15 |
| Gyro sensitivity at ±500 dps | 65.5 LSB/dps, tolerance ±1.5 % | Table 1 |
| **Gyro zero-rate offset (ZRO)** | **±5 dps** initial; ±0.05 dps/°C | Table 1 |
| Accel sensitivity at ±8 g | 4,096 LSB/g; **initial tolerance ±0.5 %**; ±0.026 %/°C | Table 2 |
| **Accel zero-g offset** | **±25 mg** component, **±50 mg** board-level; **±0.80 mg/°C** | Table 2 |

⚠️ Tolerances marked note 2 in the datasheet are *"derived from validation or characterization of
parts, not guaranteed in production."* They bound what is typical, not what is possible.
