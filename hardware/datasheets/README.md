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
| Analog Devices (Maxim) **MAX17048** fuel gauge | [`max17048/max17048-max17049.pdf`](max17048/max17048-max17049.pdf) | 19-6171 Rev 7, 11/16 | 2026-09-22 (saved by the CIO — the host resets automated requests) | `https://www.analog.com/media/en/technical-documentation/data-sheets/max17048-max17049.pdf` | `70dc8eef0e012276dcdc58b6dce64af08258304bcf865ceace64e856b8029330` |
| Geekworm **X1209** UPS HAT | [`x1209/X1209 - Geekworm Wiki.html`](x1209/) + its `_files/` folder (keep together — the page links them) | wiki page, incl. comments to 2026-05-20 | 2026-09-22 (saved by the CIO — the site returns 403 to automated requests) | `https://wiki.geekworm.com/X1209` | `262823681866e7e221020fe167633059bf94a30ba8cfe4cc3ff2d96b13fac4b3` |

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

## Facts verified against MAX17048 datasheet 19-6171 Rev 7 (2026-09-22)

| Fact | Datasheet |
|---|---|
| Registers (16-bit words only; 8-bit writes have no effect) | `VCELL 0x02` 78.125 µV/cell · `SOC 0x04` 1 %/256 (upper byte = 1 %) · `MODE 0x06` W, default 0x0000 · `VERSION 0x08` · `HIBRT 0x0A` default 0x8030 · `CONFIG 0x0C` · `VALRT 0x14` · `CRATE 0x16` · `VRESET/ID 0x18` · `STATUS 0x1A` · `CMD 0xFE` |
| **What powers it** | **VDD pin: "Power-Supply Input … MAX17048: connect to positive battery terminal."** VCELL is measured VDD–GND. ⇒ the gauge is powered by the cell |
| `STATUS.RI` | *"set when the device powers up. Any time this bit is set, the IC is not configured, so the model should be loaded and the bit should be cleared."* |
| **Battery swap** | *"If VCELL falls below VRST, the IC quick-starts when VCELL returns above VRST. **This handles battery swap.**"* |
| **Quick-start** | *"**Most systems should not use quick-start** because the ICs handle most startup problems transparently."* POR includes a quick-start. |
| Battery insertion | Assuming a relaxed cell, the first VCELL becomes the initial SOC estimate; unrelaxed error *"diminishes over time … no long-lasting impact."* |
| Temperature | **No temperature measurement.** Host must compensate RCOMP *"at least once per minute"*: `RCOMP = RCOMP0 + (T−20)·TempCoUp` (T>20) or `·TempCoDown`; defaults **RCOMP0 0x97, TempCoUp −0.5, TempCoDown −5.0** |
| `CRATE` | 1 LSb = 0.208 %/hr, *"not for conversion to ampere"* |
| Hibernate | Entered automatically at low charge/discharge rate; **VCELL and SOC then update only once per 45 s** |

## Facts verified against the Geekworm X1209 wiki (saved 2026-09-22)

| Fact | Wiki |
|---|---|
| **Charge current** | **2.1 A default** — *"IMPORTANT!! Please confirm before connecting your battery"* |
| Charge cut-off / recharge | **4.23 V cut-off; recharge threshold 4.1 V** |
| Cells | 3.7 V lithium, full charge 4.2 V — 18650, 21700, 4680 and similar. **Parallel only — series burns the board out** |
| **Protected cells** | Geekworm reply in the page comments: *"Please do not use batteries with built-in protection circuits. The X1209 already integrates protection circuitry, and protected batteries may conflict."* ⚠️ a comment reply, not the spec table |
| Output | 5.1 V, up to 6 A, with 2.1 A charging while powering the system; power-path management |
| Charging control | Via GPIO |
