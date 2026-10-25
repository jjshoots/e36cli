# BMW MS41.x (DS2) — Data Research

Scope: **what data exists, where it lives, how to decode it**. Protocol framing is covered by a
separate research task; only the minimum framing needed to interpret payloads is repeated here.

Target vehicle: **M52B25 running an M52B28 ("2.8") DME, possibly tuned.**

Confidence legend:
- **[high]** — primary source (vendor doc, ECU disassembly-derived project, or multiple independent confirmations incl. hardware verification claims)
- **[medium]** — single credible community source, or derived/inferred from a capture
- **[low]** — assumption, extrapolation, or a source that itself hedges

> **Licensing note.** The single richest machine-readable source found
> (`CAATZ/BimmerStein-ECU-Tool`) is **GPL-3.0**. Facts (addresses, scaling constants, code
> numbers) are not copyrightable, but *do not copy its Python source* into this project unless
> you intend to be GPL. Everything below is restated as data, not code.
> The `ms4x.net` wiki and RomRaider forum content is quoted as short excerpts for research.

---

## 0. Primary sources

| # | Source | URL |
|---|--------|-----|
| S1 | MS4X Wiki — Siemens MS41 | https://www.ms4x.net/index.php?title=Siemens_MS41 |
| S2 | MS4X Wiki — BMW DS2 Serial Protocol | https://www.ms4x.net/index.php?title=BMW_DS2_Serial_Protocol |
| S3 | MS4X Wiki — Diagnostic Trouble Code Translation | https://www.ms4x.net/index.php?title=Diagnostic_Trouble_Code_Translation |
| S4 | MS4X Wiki — Siemens DTC Data Explained | https://www.ms4x.net/index.php?title=Siemens_DTC_Data_Explained |
| S5 | MS4X Wiki — Siemens Keyword Translation | https://www.ms4x.net/index.php?title=Siemens_Keyword_Translation |
| S6 | MS4X Wiki — How to connect | https://www.ms4x.net/index.php?title=How_to_connect |
| S7 | RomRaider forum — "DS2 - datalogging MS41/42/43 by serial protocol" (520 posts, 2014→) | https://www.romraider.com/forum/viewtopic.php?t=11086 |
| S8 | RomRaider forum — "*** MS41 ECU & Logger Definitions ***" | https://www.romraider.com/forum/viewtopic.php?t=10695 |
| S9 | RomRaider source — `src/main/java/com/romraider/io/protocol/ds2/iso9141/*` | https://github.com/RomRaider/RomRaider |
| S10 | CAATZ/BimmerStein-ECU-Tool (GPL-3.0) — `dtc.py`, `live_data.py`, `ds2.py`, `ecu_info.py`, `ms41.py`, `logger_definitions/BimmerStein MS41 Logger Definitions.xml` | https://github.com/CAATZ/BimmerStein-ECU-Tool |
| S11 | R3VLimited — "MS41 Software Versions Archive" (SP-Daten MDS410/411/412 Zusbauvorschrift dump) | https://www.r3vlimited.com/board/forum/e30-technical-forums/24v-engine-swaps/m50-52-s50-52/9977752-ms41-software-versions-archive |
| S12 | ms4x-net/ms41 — TunerPro XDF definitions for MS41 (ZB 1429861) | https://github.com/ms4x-net/ms41 |
| S13 | dschultz "DS2 Serial Commands" Google Sheet (linked from S7) — **access-gated, could not retrieve** | https://docs.google.com/spreadsheets/d/1l7QOeayNgD6e2d99U2F5XZE8wlpgFHyvxOZdqfDqd1A/edit |
| S14 | OpenMS41 project site (mrf582 / "MS41 Project Leader") | https://sites.google.com/site/openms41/ |

**Important negative result:** the MS4X wiki page `BMW DS2 Serial Protocol` (S2) is a **stub** —
its entire wikitext content is the literal string `asdf`. `Siemens DTC Data Explained` (S4) is
likewise a stub containing only `tbc`. The ms4x wiki is *not* the gold mine for DS2 live data;
RomRaider's source (S9) and BimmerStein (S10) are. `TunerPro Data Logging` on the wiki also
contains no MS41 addresses — it only links to S2.

---

## 1. MS41 variants

### 1.1 Canonical split

> "This ECU came in three different subversions and each of them was intented to run a different
> engine or emissions class:
> **MS41.0:** M52 — **MS41.1:** M52 OBDII — **MS41.2:** S52 US"
> — S1 [high]

Hardware common to all: **Infineon/Siemens C166 (SAB 80C166) @ 20 MHz**, 88-pin connector,
256 kB flash (Intel 28F200BB or AMD/JEDEC 29F200/29F400), 1995–2000 production. (S1 [high],
S10 `ms41.py` header [high])

Practical reading:
- **MS41.0** = RoW/Euro M52 (320i/323i/328i/520i/523i/528i/728i/Z3 2.8, 323ti, Land Rover
  Defender 2.8i, M52B24 Thailand). No OBD-II P-code layer activated in Europe. [high, S11]
- **MS41.1** = US/OBD-II M52 (E36 328i/323is, E39 528i, Z3 2.8 US) **and** the Euro Alpina
  B10 3.2 (S52B32) — so MS41.1 is *not* strictly "M52 only". [high, S11]
- **MS41.2** = US S52B32 (E36 M3, Z3 M Roadster/Coupe). [high, S1+S11]
- **MS41.3** = *community custom firmware*, not a BMW variant. Derived from the MS41.2
  1406464 program by "SS1v2"/openms41; shows ECU-ID string `SHINDE1`. Mentioned because tools
  and definitions reference it. [high, S10 + S7]

### 1.2 Hardware (HW-NR) / program numbers seen in the field

From the SP-Daten `Zusbauvorschrift` tables (S11) [high]. Columns are
`ZB-NR, TYP-NR, HW-NR, (IX), SW-NR, …`.

| Variant | HW-NR (= "base program" / ECU ID) | Typical application |
|---|---|---|
| MS41.0 (MDS410, early) | `1427703` | E36 320i/323i/328i Euro, 1/95–8/95 |
| MS41.0 (MDS411) | `1429861` | the big Euro family: 320i, 323i, 328i, 520i, 523i, 528i, 728i, Z3 2.8 Euro, 323ti, Defender 2.8i |
| MS41.0 | `1440176` | E36 323ti Compact Euro from 6/99 |
| MS41.0 | `7505858` | Z3 2.8 Dubai |
| MS41.1 | `1437806` | **E36 328i USA (from 3/96), E36 323is USA, E39 528i USA 1997, Z3 2.8 USA** |
| MS41.1 | `1437804` | E39 528i Sedan USA 1998 (has DM-TL leak pump), Alpina B10 3.2 (S52B32) |
| MS41.2 | `1406464` | E36 M3 USA (manual + auto), Z3 M Roadster/Coupe USA |

Additional ECU-ID strings that MS41 tooling recognises but that are not in the S11 table:
`1405854`, `1429373`, `1432401`, `1438068`, `1438137` (S10 logger XML + `ms41.py`) [medium].
Note `1438068` and `1438137` appear in S11 as **SW-NRs** (`1438068DA`, `1438137DA`), not HW-NRs —
so at least one tool is keying on software numbers in the same namespace. **Treat the ECU-ID →
variant map as a lookup table, not a parseable rule.** [medium]

Example full S11 rows relevant to the target car:
```
1438067,1430251,1437806,A,1438068DA,FFFFFFFFFFG,088,1 U  MS41.1 E36 328i All body styles USA From 3/96
1438071,1430250,1437806,A,1438072DA,0FFE45A153H,088,1 O  MS41.1 E36 323is Coupe USA From 10/97
1438065,1744385,1437806,A,1438066DA,FFFFFFFFFFG,088,1 I  MS41.1 E39 528i Sedan USA 1997
7500903,1430252,1437806,A,7500904DA,0FFFFFFFFFD,088,1 Z  MS41.1 Z3 2.8 USA
```
So an **M52B28 US "2.8" DME is almost certainly HW `1437806`, ZB `1438067`, SW `1438068DA`** —
i.e. **MS41.1**. If the car is Euro-market the same "2.8" tag would instead point at HW
`1429861` (MS41.0) with ZB 1429954/1429955/1438745/1438790 etc. [high]

### 1.3 Telling variants apart from a live ECU

Four independent signals, in rough order of reliability:

1. **ECU-ID = first 7 ASCII bytes of the IDENT (cmd `0x00`) payload** → look up in the table
   above. This is the *hardware/base-program* number. [high, S9 `DS2EcuInit`, S10 `ds2.identify`]
2. **CAL-ID first two characters** — read the 8-byte CAL ID. Family prefix mapping
   (S10 `ms41.py`, "verified against real dumps + RomRaider MS41 definitions") [high]:
   | prefix | variant |
   |---|---|
   | `41`, `42`, `59`, `85` | MS41.0 |
   | `60` | MS41.1 |
   | `12` | MS41.2 (and MS41.3, which inherits the prefix) |
   Live addresses: CAL ID at **DS2 `0x1000E`, 8 bytes**; calibration compatibility ID at
   **DS2 `0x1000C`** (4 ASCII digits); program compatibility ID at **DS2 `0x2007`**. In a
   256 kB file image these are `0x1400E`, `0x1400C`, `0x6007`. [medium — single source S10]
3. **IDENT field "software index"** (bytes 29–31 of the ident payload) — in the one worked
   example available it reads `60`, matching the MS41.1 CAL prefix. Promising cross-check but
   **n=1**. [low]
4. **Program part number**: 7 ASCII digits at **DS2 `0x2025`** (file `0x6025`). [medium, S10]

MS41.3 (custom) discriminators, if you care: calibration marker `"SS1v2"` at DS2 `0x133BB`,
credit string `"ABHISHEK"` at DS2 `0x15F60`, program signature `9A 11 63 90` at file `0x39A9A`.
[medium, S10]

**Address translation gotcha:** BimmerStein notes that DS2/CPU addresses in the low region map to
file offsets by **XOR 0x4000** (e.g. DS2 `0x1D07` ↔ file `0x5D07`; DS2 `0x023C` ↔ file `0x423C`).
Memory map from S1 is in *file* order: `00000-07FFF` bootloader+UIF, `08000-0FFFF` undocumented,
`10000-15FFF` calibration (24 kB), `16000-1FFFF` undocumented, `20000-3FFFF` program (128 kB).
BimmerStein instead describes the live tune partition as DS2 `0x10000-0x15FFF` ← file
`0x14000-0x17FFF` then `0x10000-0x11FFF`. **These two descriptions conflict; see §7.** [conflict]

### 1.4 "M52B25 with a 2.8 ECU, possibly tuned"

Consequences for the CLI:
- The ident string will say `1437806` (US) or `1429861` (Euro). The DME does **not** know the
  engine is a 2.5 — load/MAF/injection scaling is all 2.8 calibration, so fuel trims will sit
  off-nominal. Expect long-term multiplicative trim pushed lean-ward.
- **A tune does not change the ECU ID or CAL-ID prefix** (tuners reflash the 24 kB calibration
  partition; the program number and UIF are untouched unless WinKFP was used). So variant
  detection stays valid, but **map-derived constants can be wrong**. RAM addresses are a
  property of the *program* half, so live-data addresses keyed on ECU-ID remain valid for a
  cal-only tune. [medium — inference from S10's program/calibration split, reasonable but verify]
- If the tuner used a different ZB via WinKFP, the ECU-ID can legitimately differ from the
  factory part on the sticker.

---

## 2. Identification response (DS2 command `0x00`)

Request: `12 04 00 16` (addr 0x12, len 4, cmd 0x00, XOR checksum). [high, S9]

Response: a normal DS2 frame `12 2E A0 <42 data bytes> <xor>` — **total 46 bytes (0x2E), 42-byte
payload**. Example captured by RomRaider (S9 comment in `DS2Protocol.java`):

```
12 2e a0 31343337383036 3131303133303231323239363030303031313538353236303030393632313432353634 9c
         └ "1437806" ──┘ └───────────── 35 further ASCII chars ─────────────────────────────┘
```

### Payload layout (42 bytes, all ASCII)

| Offset | Len | Field | Example (from the capture above) |
|---|---|---|---|
| 0 | 7 | **ECU / BMW hardware part number** (the "ECU ID") | `1437806` |
| 7 | 2 | BMW hardware number (index) | `11` |
| 9 | 2 | **Coding index** | `01` |
| 11 | 2 | Diagnostic index | `30` |
| 13 | 2 | Bus index | `21` |
| 15 | 2 | Manufacturing week (digits) | `22` |
| 17 | 2 | Manufacturing year (digits) | `96` |
| 19 | 10 | Supplier number | `0000115852` |
| 29 | 2 | **Software index** | `60` |
| 31 | 2 | Change index | `00` |
| 33 | 9 | DME production serial (digits) | `962142564` |

Source: S10 `ecu_info.decode_identification()`, described there as "the 42-byte normal-runtime
IDENT payload described by BMW PRGs". Field *names* [high]; the exact offsets are from one
implementation and the worked example above is self-consistent (7+2+2+2+2+2+2+10+2+2+9 = 42)
[medium].

Extras:
- **EWS2 ISN = the last 4 ASCII digits of the ident payload** (= last 4 of the production
  serial). [medium, S10 `_isn_from_identify`]
- RomRaider only uses the first 7 bytes and calls that the `ecuId`. [high, S9 `DS2EcuInit`]
- If the payload length is not exactly 42, treat all fields except the leading 7 as unknown.

### Related identity reads (all via cmd `0x06` memory read)

| Item | DS2 address | Len | Notes |
|---|---|---|---|
| VIN (6-bit packed) | `0x1D07` | 13 | 4 chars per 3 bytes, charset `0-9A-Z`, decode then drop first 3 chars → 17-char VIN. Lives in the protected boot block, survives reflash. [medium, S10; cross-ref `sprytnyk/mscoder`] |
| DME production serial block | `0x1CE0` | 14 | marker `"1585"` at +0, 9-digit serial at +5 |
| Program part number | `0x2025` | 7 | ASCII digits |
| Program compat ID | `0x2007` | 4 | ASCII digits |
| Calibration compat ID | `0x1000C` | 4 | ASCII digits |
| CAL ID | `0x1000E` | 8 | first 2 chars = family |
| Coding family | `0x1CF4` | 3 | ASCII digits |
| Flash driver signature | `0x023C` | 8 | `E0 0E 0D 58 F0 4E C0 84` = AMD (29F200/29F400); `E6 F4 50 00 B8 4C 6F E0` = Intel (28F200) |
| AIF programming history (MS41.2/.3 only) | `0x1D07`-region, file `0x5D07` | 14 × 0x2E | append-only; current record = last non-`FF`. ZB at rec+0x1B..0x1D (3-byte BE int), SW number at rec+0x11..0x13, packed date at rec+0x0E/0x0F (`day = b[0x0E]>>3`, `month = ((b[0x0E]&7)<<1)\|(b[0x0F]>>7)`, `year = 1900 + (b[0x0F]&0x7F)`) |
| AT/MT flag | `0xFD5C` (MS41.1/.2/.3), `0xFD4C` (MS41.0) | 1 | bit 7 set = automatic |

All [medium] — single source (S10), but internally consistent and claimed verified against real
dumps. S11 independently says the ZB number lives at file `0x5D22-0x5D24` for the first entry and
`0x5D50-0x5D52` for the second — which matches a 0x2E (46-byte) record stride and the +0x1B field
offset (`0x5D07 + 0x1B = 0x5D22`, `0x5D07 + 0x2E + 0x1B = 0x5D50`). **Two independent sources
agree on the AIF geometry.** [high]

---

## 3. Live data

### 3.1 There are *three* different live-data mechanisms on MS41

| Mechanism | Command | What you get | Use |
|---|---|---|---|
| **A. Fixed status group read** | `0x0B <group>` | a fixed-layout record (EDIABAS `STATUS_*` jobs) | simplest, works stock, but the record layout is only partly reverse-engineered publicly |
| **B. ADC channel read** | `0x0B 0x02 0x0E 0x00 0x00 <ch>` | one 2-byte ADC value | single sensor voltages |
| **C. Direct RAM read** | `0x06 <addr32> <len>` | arbitrary RAM/ROM bytes | **the one with a fully documented parameter table** |
| **D. Registered "telegram" batch** | `0x0B 0x01` setup, then `0x0B 0x00` poll | 24 parameters in one 38-byte response | fastest; MS41-specific |

**Recommendation for the CLI: build on C (+ D as a speed optimisation).** C is the only path
with a complete, public, address→scaling table.

### 3.2 Command reference (payload-level)

From RomRaider `DS2Protocol.java` (S9) [high] and BimmerStein `ds2.py` (S10) [high]; agree:

| Cmd | Name | Args | Notes |
|---|---|---|---|
| `0x00` | IDENTIFY | — | §2 |
| `0x04` | READ_DTC (FS_LESEN) | 1 byte sub | §4 |
| `0x05` | CLEAR_DTC | — | **WRITE** |
| `0x06` | READ_MEMORY | `addr[4] BE` + `len[1]` | len 1..247 (`0xF7`). RomRaider comments the form as `12 09 06 <seg> <addr_hi> <addr_lo> <nbytes>` — i.e. a 24-bit address with a leading segment byte, which is the same thing as a 4-byte BE address with a zero MSB. |
| `0x07` | FLASH_OP | — | **WRITE / destructive** |
| `0x0B` | TELEGRAM / status group | see below | |
| `0x0B 0x00` | poll registered batch | `0x0B 0x00 <session>` | RomRaider calls this `READ_ADDRESS_COMMAND` |
| `0x0B 0x01` | register batch | `0x0B 0x01 <session> …` | RomRaider calls this `SET_ADDRESS_COMMAND` |
| `0x0B 0x02` | read procedure / ADC | `0x0B 0x02 0x0E 0x00 0x00 <ch>` | RomRaider: `READ_PROCEDURE_COMMAND`, with explicit "legacy ADC def 0x0B020E support" |
| `0x0B 0x03` | STATUS_MOTORDREHZAHL group | — | 25-byte record, see §3.3 |
| `0x0B 0x04` | STATUS_DIGITAL | — | 3-byte bitfield, see §3.5 |
| `0x0D` | STATUS | — | BimmerStein: "returns 69-byte ECU status payload" — **contents undocumented** |
| `0x14` | READ_SHADOW_DTC (FS_SHADOW_LESEN) | `0x01` | §4 |
| `0x43` | CLEAR_ADAPTATIONS | 1–2 bytes | **WRITE**, §6 |
| `0x90` | SEED_KEY | | write-unlock |
| `0xA2` | PREPARE | | flash |

Response status byte (the byte right after the length): `A0` = OK. BimmerStein's module-scan
code gives the fuller set [medium, S10 `vehicle_diagnostics.py`]:

| Byte | Meaning |
|---|---|
| `A0` | Responded / OK |
| `A1` | Busy |
| `A2` | Request rejected |
| `B0` | Invalid parameter |
| `B1` | Unsupported function |
| `B2` | Unsupported number |
| `FF` | Negative acknowledgement |

Link settings for DS2 on MS41: **9600 baud, 8 data bits, 1 stop bit, even parity (parity=2),
no init sequence**, connect timeout 2000 ms, inter-command gap ~55 ms. Checksum = XOR of all
preceding bytes. Module address `0x12` = DME. [high — S9 `getDefaultConnectionProperties()` and
S10 both say 9600 8E1/8E2]

Other DS2 module addresses on these cars (useful for a scan feature): `0x32` EGS auto trans,
`0x44` EWS, `0x56` ABS/ASC, `0x5B` IHKA, `0xA6` cruise. [medium, S10]

### 3.3 Mechanism A — fixed status group `0x0B 0x03`

Captured EDIABAS trace from S7 (job `STATUS_MOTORDREHZAHL`, MS41.1 variant `MS411DS1`) [high]:

```
INPUT : 12 05 0B 03 <xor>
OUTPUT: 12 1D A0 | 00 00 00 24 00 00 D3 E0 4F 00 00 24 5C 98 7C 00 7E 80 00 80 00 06 06 00 00 | 15
```
→ 29-byte frame (`0x1D`), **25 data bytes**.

Six aligned samples posted by mrf582 (S7), annotated with the EDIABAS-reported coolant temp:

```
                                                                    ECT      state
12 1D A0 02 BF 00 26 17 AB 4E 41 59 02 49 07 24 6A 88 22 7F 80 00 80 00 38 38 CE CE 09   78.75  idle
12 1D A0 00 00 00 26 00 00 48 3F 4F 00 00 0C DE 70 F4 00 74 80 00 80 00 06 06 06 06 93   79.65  ignition on
12 1D A0 02 C0 00 26 14 5D 54 3E 69 01 EA 03 74 61 CC 1D 7F 80 00 80 00 39 39 CE CE 52   80.10  idle
12 1D A0 00 00 00 26 00 00 47 3E 4F 00 00 0C BC 70 D8 00 74 80 00 80 00 06 06 06 06 D3   80.10  ignition on
12 1D A0 07 C3 00 34 13 95 5C 36 78 01 F7 00 E0 87 8C 1C 80 80 00 80 00 37 37 C2 C2 4A   83.70  2000 rpm
12 1D A0 08 48 00 33 11 DF 5D 33 8A 01 C6 00 00 85 EC 20 81 80 00 80 00 38 38 C1 C1 F9   85.05  2000 rpm
```

Decoded so far (indices are into the 25 **data** bytes, i.e. frame byte 3 = data[0]):

| data[] | Parameter | Decode | Confidence |
|---|---|---|---|
| 0..1 | **Engine RPM** | uint16 **big-endian**, direct rpm (`0x02BF`=703 idle, `0x07C3`=1987, `0x0848`=2120) | [high] — stated by mrf582 and verified against the samples |
| 7 | **Coolant temperature** | `°C = 108 − 0.45 × raw` (mrf582: "multiplier −0.45, offset 108"); `0x41`=65 → 78.75 °C ✓, `0x3F`→79.65 ✓, `0x33`→85.05 ✓ | [high] — derived and verified on 6 points |
| 2 | always `00` in all samples | likely an RPM high byte or padding | [low] |
| 3 | `0x26` at idle/KOEO, `0x33–0x34` at 2000 rpm | candidate load or MAF | [low] |
| 4..6, 8..24 | unknown | mrf582 says he also decoded air temp, vehicle speed, load (mg/stroke), VANOS angle, ignition angle, injection time, MAF kg/h, MAF volts, TPS volts from these traces, **but the spreadsheet (S13) is access-gated** | [unknown] |

**This is the key documentation gap.** The full `0x0B 0x03` record layout exists (S13 + the
RomRaider DS2 logger XML attachment in S8) but both are behind a login. See §7.

### 3.4 Mechanism B — ADC channel read `0x0B 0x02 0x0E 0x00 0x00 <ch>`

Captured trace (S7, job `STATUS_LS_VKAT_SIGNAL_1`, "voltage of the pre-cat lambda sensor"):
```
INPUT : 12 09 0B 02 0E 00 00 01 <xor>
OUTPUT: 12 06 A0 00 FA 4E        → payload 0x00FA = 250 → EDIABAS reported 4.825 V
```
⇒ **volts = raw × 0.0193** for this channel (250 × 0.0193 = 4.825). [high for this one channel]

Known channel numbers:

| ch | Signal | Scaling | Source |
|---|---|---|---|
| `0x01` | Pre-cat lambda sensor bank 1 voltage | `V = raw × 0.0193` | S7 capture [high] |
| `0x07` | **Battery voltage (STATUS_UBATT)** | `V = raw(BE16) × 0.101` | S10 `read_battery_voltage()` [high] — BimmerStein calls it "BMW's universal STATUS_UBATT telegram" |

The DTC freeze-frame table (§4.3) lists `0.0196 V/bit` for O2 sensor voltage and
`0.1020 V/bit` for battery — essentially the same constants, so **0.0193 vs 0.0196 is rounding
noise; use ~0.0196 (= 5.0/255) and 0.1020**. [medium]

RomRaider's `0x0B 0x02` is also used generically for "procedures", so other channels exist but
were not enumerated by any accessible source.

### 3.5 Mechanism A′ — `0x0B 0x04` STATUS_DIGITAL bitfield

Capture (S7): `12 05 0B 04` → `12 07 A0 21 00 01 95` — **3 data bytes of flags**. Bit table
recovered from Tool32 for `MS411DS1` and posted by `blarf` (S7) [high]:

| Name | Byte | Mask | Meaning |
|---|---|---|---|
| `S_LL` | 0 | `0x01` | idle switch (note: listed with VALUE 0x00) |
| `S_VL` | 0 | `0x03` | full load |
| `S_ASC` | 0 | `0x04` | ASC active |
| `S_MSR` | 0 | `0x08` | MSR (engine drag torque control) |
| `S_DWA` | 0 | `0x20` | alarm system |
| `S_AC` | 0 | `0x40` | A/C request |
| `S_KO` | 0 | `0x80` | A/C compressor |
| `S_CAN` | 1 | `0x01` | CAN |
| `S_GE` | 1 | `0x02` | transmission (Getriebe) |
| `S_FS` | 1 | `0x04` | driving-mode/road speed |
| `S_REG1` | 1 | `0x40` | lambda control bank 1 active |
| `S_REG2` | 1 | `0x80` | lambda control bank 2 active |
| `S_EKP` | 2 | `0x01` | electric fuel pump |
| `S_KO_REL` | 2 | `0x02` | compressor relay |
| `S_VANOS` | 2 | `0x04` | **VANOS active** |
| `S_KLAPPE` | 2 | `0x08` | exhaust flap |
| `S_RUN_LOSSES` | 2 | `0x10` | run-losses (EVAP) |
| `S_AAV` | 2 | `0x20` | secondary air valve |
| `S_SLP` | 2 | `0x40` | secondary air pump |
| `S_SLV` | 2 | `0x80` | secondary air valve 2 |
| `S_ABGAS` | 3 | `0x04` | exhaust — **byte index 3 exceeds the 3-byte response; table is from a larger/other variant** |

Caveat noted in the same thread: EDIABAS also reports `STATUS_SCHUB_AB_EIN` (overrun fuel cut)
which is **not** in this bit table. [high]

### 3.6 Mechanism C — RAM parameter table (the main event)

Read with `0x06 <addr32 BE> <len>`, max 247 bytes per read. Addresses below are **absolute
24-bit C166 logical / DS2 addresses**. Multi-byte values in RAM are **little-endian**.

Source: `BimmerStein MS41 Logger Definitions.xml` (S10), which is a RomRaider-format logger
definition. It carries per-ECU-ID address variants. RomRaider's own DS2 logger definition (S8
attachment) is the upstream lineage but is login-gated; the BimmerStein file reuses RomRaider's
parameter IDs (`P2`, `P8`, `P11`, `P12`, `P17`, `E9`, `E11`, `E13`, `E14`, `E21`, `E22`, `E24`,
`E217`), which independently confirms the ID namespace against RomRaider's
`DS2Parameter.java` (S9). [address values: medium-high; parameter ID semantics: high]

#### 3.6.1 Common across all listed ECU IDs
(ECU IDs: `1405854, 1406464, SHINDE1, 1429373, 1429861, 1432401, 1437806, 1440176`)

| Param | Name | DS2 addr | Type | Scaling | Unit |
|---|---|---|---|---|---|
| `P8` | **Engine RPM** | `0xDA2A` | uint16 LE | `x` | RPM |
| `P12` | **Mass Air Flow** | `0xDA34` | uint16 LE | `x × 0.25` | kg/h |
| `E9` | Idle valve position | `0xDA36` | int16 LE | `x × 0.00153` | % |
| `P11` | **Intake air temp** | `0xDA50` | uint8 | `x × 0.747 − 48` | °C |
| — | EVAP purge duty (CPV) | `0xDA56` | uint8 | `x × 100/255` | % |
| `P2` | **Coolant temp** | `0xDA5A` | uint8 | `x × 0.747 − 48` | °C |
| `P9` | **Vehicle speed** | `0xDA63` | uint8 | `x` | km/h |
| `P10` | **Ignition advance** | `0xE989` | uint8 | `0.373 × x − 23.6` | ° |
| `E217` | **Knock retard (current)** | `0xE98D` | uint8 | `(x − 128) × 0.375` | ° |
| `E24` | Knock retard (global) | `0xE9D9` | uint8 | `(x − 128) × 0.375` | ° |
| `E11` | **VANOS measured angle** | `0xE9E6` | uint8 | `x × 0.3745` | ° |
| — | Front O2 bank 1 ADC | `0xFA9A` | uint16 LE | `(x & 0x3FF) × 5 / 1023` | V |
| — | Front O2 bank 2 ADC | `0xFA98` | uint16 LE | `(x & 0x3FF) × 5 / 1023` | V |
| `P18` | MAF sensor ADC | `0xFA9E` | uint16 LE | `(x & 0x3FF) × 5 / 1023` | V |
| — | engine-state flag byte | `0xFD24` | uint8 | bit 0 = **closed throttle** (inverted), bit 1 = **full load** | — |
| — | operating-state flag byte | `0xFD14` | uint8 | bit 1 = **engine start**, bit 3 = **part load**, bit 5 = **decel fuel cut** | — |

Also known from the same project (not in the logger XML but in `live_data.py`) [medium]:

| Item | Addr | Notes |
|---|---|---|
| Other ADC sources | `0xE8DA` TPS voltage, `0xFAA2` TPS base voltage, `0xFA96` rear O2 B1, `0xFA94` rear O2 B2, `0xF5A8` EVAP pressure | same 10-bit `(x & 0x3FF) × 5/1023` form |
| Knock adaptation tables | `0xD840`, 6 tables × 0x40 bytes, each 16 rows × 4 cols | value `(b − 128) × 0.375` ° |
| Throttle adaptation | `0xE8DE` | int16 LE × `0.001526` |

#### 3.6.2 Per-ECU-ID addresses (**these move between variants — do not hardcode one set**)

| Parameter | `1429861` (MS41.0) | `1437806` (MS41.1) | `1406464`/`SHINDE1` (MS41.2/.3) | Type / scaling |
|---|---|---|---|---|
| **Throttle position** `P13` | `0xE8D0` | `0xE8D0` | `0xE8D0` | uint8, `x × 100/255` % (only defined for 1406464/SHINDE1/1429861/1437806) |
| **Injector pulse width** | `0xECBC` | `0xEF96` | `0xEF7E` | uint16 LE, `x × 0.00534` ms |
| **Short-term fuel trim B1** `E13` | `0xED5C` | `0xF036` | `0xF01E` | uint16 LE, `(x − 32768) × 100/65535` % |
| **Short-term fuel trim B2** `E14` | `0xED96` | `0xF0F2` | `0xF0CA` | same |
| **Long-term fuel trim B1** `E21` | `0xED6E` | `0xF048` | `0xF030` | same |
| **Long-term fuel trim B2** `E22` | `0xEDA8` | `0xF104` | `0xF0DC` | same |
| **Additive fuel trim B1** | `0xED66` | `0xF040` | `0xF028` | uint16 LE, `(x − 32768) × 0.00534` **ms** |
| **Additive fuel trim B2** | `0xEDA0` | `0xF0FC` | `0xF0D4` | same |
| **Engine load** `E2` | `0xFAFC` | `0xFC52` | `0xFC52` | uint16 LE, `x × 0.021195` mg/stroke (full-scale 1389) |
| **Battery voltage** `P17` | `0xFB47` | `0xFC9D` | `0xFC9D` | uint8, `x × 0.10196` V |
| Lambda regulation active B1 | `0xED58` | `0xF032` | `0xF01A` | uint8, bit 3 |
| Lambda regulation active B2 | `0xED92` | `0xF0EE` | `0xF0C6` | uint8, bit 3 |
| Front O2 heater B1 duty | `0xEDE3` | `0xF1AF` | `0xF189` | uint8, `x × 100/255` % |
| Front O2 heater B2 duty | `0xEDEB` | `0xF1B7` | `0xF191` | uint8, `x × 100/255` % |
| Rear O2 heater B1 duty | — | `0xF07C` | `0xF064` | uint8, `x × 100/255` % |
| Rear O2 heater B2 duty | — | `0xF138` | `0xF110` | uint8, `x × 100/255` % |
| Runtime cut RPM | `0xFAE6` | `0xFC3C` | `0xFC3C` | uint8, `x × 32` RPM |
| Launch/runtime speed | `0xEDF4` | `0xF1BE` | `0xF19A` | uint8 km/h |

**For the target car (M52B28 ECU, US → `1437806`) use the MS41.1 column.** If the ident returns
`1429861`, use the MS41.0 column. If it returns anything else in the ID list, only the §3.6.1
common set is safe.

Note the three distinct "fuel trim" quantities, which answers the additive/multiplicative
question directly:
- **Multiplicative (factor) trims** — `E13`/`E14` short-term and `E21`/`E22` long-term, expressed
  as a **%** around a 0x8000 midpoint. These are the classic BMW "Lambdaregelung" /
  "Gemischadaption multiplikativ".
- **Additive trims** — the `0xED66`/`0xF040`/`0xF028` family, expressed in **milliseconds** of
  injector time around a 0x8000 midpoint, scale `0.00534 ms/LSB` — the same LSB as injector
  pulse width, which is a strong internal consistency check. [high confidence in the
  interpretation; medium in the addresses]

Fuel-adaptation *stored* (non-volatile) pairs used by the adaptation-read feature [medium, S10]:

| ECU ID | Bank 1 (additive, multiplicative) | Bank 2 (additive, multiplicative) |
|---|---|---|
| `1429861` | `0xED66`, `0xED6E` | `0xEDA0`, `0xEDA8` |
| `1437806` | `0xF040`, `0xF048` | `0xF0FC`, `0xF104` |
| `1406464`/`SHINDE1` | `0xF028`, `0xF030` | `0xF0D4`, `0xF0DC` |

Knock-adaptation table axes (calibration-side, read via DS2 at these addresses) [medium]:

| ECU ID | Load axis (4 bytes, `v × 1389/255` mg/stroke) | RPM axis (16 bytes, `v × 32` RPM) |
|---|---|---|
| `1437806` / `1438068` | `0x12606` | `0x125D9` |
| `1429861` / `1432401` | `0x1239A` | `0x1236D` |
| `1429373` | `0x12144` | `0x12117` |
| `1406464` / `SHINDE1` | `0x12388` | `0x1235B` |

#### 3.6.3 Priority-parameter coverage summary

| Requested | Available? | Where |
|---|---|---|
| RPM | ✅ | RAM `0xDA2A` uint16 LE; also group `0x0B 03` data[0:2] BE |
| Coolant temp | ✅ | RAM `0xDA5A`, `0.747x − 48` °C; group `0x0B 03` data[7], `108 − 0.45x` |
| Intake air temp | ✅ | RAM `0xDA50`, `0.747x − 48` °C |
| MAF (mass air flow) | ✅ | RAM `0xDA34` uint16 LE × 0.25 kg/h; raw ADC volts at `0xFA9E` |
| Throttle position | ✅ | RAM `0xE8D0` × 100/255 %; raw TPS volts `0xE8DA` / `0xFAA2` |
| Lambda / O2 | ✅ | front B1 `0xFA9A`, front B2 `0xFA98`, rear B1 `0xFA96`, rear B2 `0xFA94` (10-bit ADC); lambda-control-active flags per bank |
| Short/long-term fuel trims (multiplicative) | ✅ | per-variant table above |
| Additive adaptations | ✅ | per-variant table above (ms) |
| Ignition timing | ✅ | RAM `0xE989`, `0.373x − 23.6` ° |
| Knock retard | ✅ | current `0xE98D`, global `0xE9D9`, `(x−128) × 0.375` ° |
| VANOS position | ✅ | measured angle `0xE9E6` × 0.3745 °; **VANOS active flag** = `0x0B 04` byte 2 bit 2 |
| Vehicle speed | ✅ | RAM `0xDA63` km/h |
| Battery voltage | ✅ | RAM (per variant) × 0.10196 V; or `0x0B 02 0E 00 00 07` × 0.101 V |
| Injector pulse width | ✅ | per-variant, uint16 LE × 0.00534 ms |
| Engine load | ✅ | per-variant, uint16 LE × 0.021195 mg/stroke |
| **Idle target (setpoint RPM)** | ❌ | **not found in any accessible live-data table.** Only the *calibration* tables `ip_n_sp_is`, `ip_dri_n_sp_is`, `ip_acin_n_sp_is`, `ip_dri_acin_n_sp_is` are documented (S1). The runtime setpoint must be in RAM but its address is undocumented. Idle *valve position* is available (`0xDA36`). |
| Oil temperature | ❌ | MS41 M52 has no oil temp sensor on the DME |

### 3.7 Mechanism D — the 24-parameter batch "telegram"

MS41-specific, **wire format verified from a serial capture** by the BimmerStein author
(S10 `ds2.py`, comment: `Wire format verified from serial capture ("Capture Live Data
Telegram.csv")`). [medium-high]

**Setup frame (sent once), 136 bytes total on the wire:**
```
12 88 0B 01 1A
   02 0E 00 00 07            ← group 1 header
   <20 entries × 5 bytes>
   02 0E 00 00 06            ← group 2 header
   <4 entries × 5 bytes>
   <xor>
```
- `0x1A` is the session id, reused in the poll.
- Entry = `[SIZE][0x00][0x00][ADDR_HI][ADDR_LO]`, `SIZE` `0x00` → 1 byte returned,
  `0x01` → 2 bytes returned. Addresses are 16-bit (RAM only).
- Group 1 entries must total **26 data bytes**; group 2 must total **8**.
- ECU replies with a bare 4-byte ACK.

**Poll:** `12 05 0B 00 1A <xor>` → 38-byte payload:
```
[0:2]   group-1 status (ignore)
[2:28]  group-1 data   (20 params, 26 bytes)
[28:30] group-2 status (ignore)
[30:38] group-2 data   (4 params, 8 bytes)
```
**Critical decoding detail:** multi-byte values in the *telegram* response are **big-endian**,
unlike raw `0x06` RAM reads which return native little-endian. The BimmerStein comment says this
was confirmed on hardware (little-endian gave wrong long-term fuel trims). [medium-high]

The stock 24-slot profile, in order (addresses per §3.6.2 for the detected ECU ID):

| # | Size | Address | Parameter |
|---|---|---|---|
| 0 | 2 | `0xDA36` | Idle valve position |
| 1 | 2 | `inj` | Injector pulse width |
| 2 | 1 | `0xE989` | Ignition advance |
| 3 | 1 | `0xE98D` | Knock retard |
| 4 | 1 | `0xDA63` | Vehicle speed |
| 5 | 1 | `tps` (`0xE8D0`) | Throttle position |
| 6 | 2 | `0xDA2A` | Engine RPM |
| 7 | 2 | `0xDA34` | Mass air flow |
| 8 | 1 | `0xDA5A` | Coolant temp |
| 9 | 1 | `0xDA50` | Intake air temp |
| 10 | 1 | `batt` | Battery voltage |
| 11 | 1 | `0xE9D9` | Global knock retard |
| 12 | 1 | `0xE9E6` | VANOS measured angle |
| 13 | 1 | `0xDA56` | CPV / EVAP purge duty |
| 14 | 2 | `lt1` | Long-term fuel trim B1 |
| 15 | 2 | `lt2` | Long-term fuel trim B2 |
| 16 | 1 | `st1+1` | Short-term fuel trim B1 (**high byte only**) |
| 17 | 1 | `st2+1` | Short-term fuel trim B2 (**high byte only**) |
| 18 | 1 | `0xFD24` | Engine-state bits |
| 19 | 1 | `0xFD14` | Operating-state bits |
| — | — | — | *group 2 boundary* |
| 20 | 2 | `load` | Engine load |
| 21 | 2 | `0xFA9A` | Front O2 bank 1 ADC |
| 22 | 2 | `0xFA98` | Front O2 bank 2 ADC |
| 23 | 2 | `0xFA9E` | MAF ADC |

Per-ECU-ID substitutions used by BimmerStein's built-in profile
(`tps, lt1, lt2, st1, st2, inj, load, batt`):
- `1406464` / `SHINDE1`: `E8D0, F030, F0DC, F01F, F0CB, EF7E, FC52, FC9D`
- default (`1437806`-class): `E8D0, F048, F104, F037, F0F3, EF96, FC52, FC9D`

(Note `st1` here is `F01F` = `F01E + 1` and `F037` = `F036 + 1` — the "+1, 1 byte, value << 8"
trick for reading only the ST trim's high byte.)

Observed poll rate ~112 ms/sample ≈ 9 Hz. RomRaider's own limit: **max 32 parameters per
request** (`DS2LoggerConnection.properties`: "Parameter request too large (maximum 32)").

### 3.8 Non-MS41 note on logging rate
The Logger.S ESP32 project reports "up to 33 Hz on MS43/42" — MS41 is substantially slower
because it lacks the MS4x extended-logging patch. (S: https://www.ms4x.net/index.php?title=Logger.S) [medium]

---

## 4. DTCs (fault codes)

### 4.1 Read / clear commands

| Operation | Frame | Response |
|---|---|---|
| Prepare / count (`FS_LESEN` sub 0) | `12 05 04 00 <xor>` | ≥5-byte payload; bytes [3:5] big-endian = **current operating-hours counter ×0.1 h**. May answer status `A1` (busy) — retry (BimmerStein retries up to 32×). |
| Read stored faults | `12 05 04 01 <xor>` | `count` byte + `count` × **10-byte** records |
| Read shadow memory (`FS_SHADOW_LESEN`) | `12 05 14 01 <xor>` | `count` byte + `count` × **11-byte** records |
| **Clear faults** (WRITE) | `12 04 05 <xor>` | ACK |

[medium-high — S10, "layout verified against an MS41 serial capture and the MS41.3 response
builder"]

Empty-DTC edge case: a stock MS41 returns payload `00 00` (count 0 plus a pad byte), not a bare
`00`.

### 4.2 Record layout

> **[verified on car 2026-10-25]** (ECU 1429373, tests/fixtures/car-dtc.jsonl):
> `04 01` answered with count=3 then 3 × 10-byte records exactly as below, plus
> **one trailing pad byte** (0x74) — payload length 31 is NOT a multiple of the
> record size; decoders must tolerate the tail. Codes 217/25/52, status
> 0x78/0x74/0x64, freq 1/13/41, hours stamps 0x42F7/0x42F7/0x42F9 all decoded
> correctly. `04 00` (prepare) answered `A0 03 00 00 43 F2` — current
> operating-hours counter at data[3:5] BE (0x43F2 → 1739.4 h), giving fault
> ages 25.1/25.1/24.9 h. No `A1 busy` seen on either command.

**Stored record (10 bytes):**

| Byte | Meaning |
|---|---|
| 0 | **DTC code** (single byte, 1–255) |
| 1 | **Status flags** |
| 2 | **Frequency** (occurrence counter) |
| 3 | Logistics counter |
| 4..7 | **Freeze-frame / environment raw values** (4 bytes — see §4.3) |
| 8..9 | Operating-hours stamp, big-endian; `hours_ago = (current_counter − value) × 0.1` |

**Shadow record (11 bytes):** same 0..7, byte 9 = operating hours (float of raw byte).

**Status flag bits (byte 1):**

| Mask | Meaning |
|---|---|
| `0x01` | Short circuit to battery positive |
| `0x02` | Short circuit to ground |
| `0x04` | Open circuit |
| `0x08` | *(no admitted BMW text)* |
| `0x10` | Emissions relevant |
| `0x20` | Stored after debounce |
| `0x40` | **Currently present / active** |
| `0x80` | Sporadic (vs static) |

Special case: code **100** (DME self-test) — bytes [6:8] little-endian carry a self-test reason
word instead of a normal freeze frame. [medium]

### 4.3 Freeze-frame ("environment") value identifiers

Each fault code has a FORTTEXTE-defined list of **four** environment source IDs; the 4 raw bytes
at record[4:8] are decoded with `value = raw × A + B`:

| ID | Label | Unit | A | B |
|---|---|---|---|---|
| `0x01` | Engine speed | rpm | 32.0 | 0 |
| `0x02` | Air mass | kg/h | 4.0 | 0 |
| `0x03` | Spark duration (low range) | ms | 0.0196 | 0 |
| `0x04` | Spark duration (high range) | ms | 2.56 | 0 |
| `0x05` | Lambda controller bank 1 | % | 0.3906 | −50 |
| `0x06` | Lambda controller bank 2 | % | 0.3906 | −50 |
| `0x07` | Oxygen-sensor voltage 1 | V | 0.0196 | 0 |
| `0x08` | Oxygen-sensor voltage 2 | V | 0.0196 | 0 |
| `0x09` | Battery voltage | V | 0.1020 | 0 |
| `0x0A` | Throttle angle | ° | 0.4686 | 0 |
| `0x0B` | Idle actuator | % | 0.3906 | 0 |
| `0x0C` | Engine load | mg/stroke | 5.4471 | 0 |
| `0x0D` | Vehicle speed | km/h | 1.0 | 0 |
| `0x0E` | Gear information | raw | 1.0 | 0 |
| `0x0F` | Camshaft angle | ° | 32.0 | 0 |
| `0x10` | Engine operating state | raw | 1.0 | 0 |
| `0x11` | Digital fault code 1 | raw | 1.0 | 0 |
| `0x12` | Digital fault code 2 | raw | 1.0 | 0 |
| `0x13` | Coolant-sensor voltage | V | 0.0196 | 0 |
| `0x14` | Mean rich oxygen-sensor value | V | 32.0 | 0 |
| `0x15` | Knock-signal gain | ratio | 0.00392 | 0 |
| `0x16` | Noise value | V | 0.02 | 0 |
| `0x17` | Oxygen-sensor heater | % | 0.391 | 0 |
| `0x18` | Coolant temperature | °C | 0.7471 | −48 |
| `0x19` | Intake-air temperature | °C | 0.7471 | −48 |
| `0x1A` | Air-flow-meter voltage | V | 0.0196 | 0 |
| `0x1B` | Tank-vent valve command | % | 0.391 | 0 |

Source: S10 `dtc.py`, described as "Hash-bound BMW FUMWELTTEXTE values. The BEST jobs apply
raw × A + B." [medium]

Note: `0x18`/`0x19` give `0.7471x − 48`, which **matches the live-RAM temperature scaling
`0.747x − 48`** found independently in the logger definition — a useful cross-validation.
It does **not** match the `0x0B 03` group-read coolant formula `108 − 0.45x`, confirming the
group read uses a different (inverted) encoding of coolant temp. [high]

The per-code environment-ID mapping is large (~95 codes); it is in S10 `dtc.py`
(`_ENVIRONMENT_BY_CODE`). Representative rows:
`0x01–0x03` (ignition coils) → `(rpm, load, spark_low, spark_high)`;
`0x05/0x06` (injectors) → `(rpm, load, Ubatt, lambda B1)`;
`0x08` (MAF) → `(rpm, throttle, idle actuator, MAF volts)`;
`0x0A` (coolant sensor) → `(rpm, load, IAT, ECT)`;
`0x64` (=100, DME self-test) → `(coolant volts, Ubatt, digital fault 1, digital fault 2)`;
most codes ≥ `0xD1` → `(rpm, load, ECT, Ubatt)`.
Variant deltas: MS41.0/MS41.1 add code `0x0B` → `(rpm, load, IAT, ECT)`; MS41.2/MS41.3 map
codes `0xBE–0xC5` → `(coolant volts, Ubatt, digital 1, digital 2)`. [medium]

### 4.4 Numeric DTC → description table

This is the BMW-internal single-byte code set (**not** OBD-II P-codes). Reproduced from S10
`dtc.py`, which cites *"openms41.sites.google.com DTC reference table (verified)"* with code 46
supplemented from BMW `MS411DS2.PRG` FORTTEXTE. [medium — one consolidated source; the upstream
openms41 table is the real authority and should be re-verified if possible]

Caveat: this table is shared across MS41/MS42/MS43 — many entries (electronic throttle, DM-TL,
pedal position sensors, SMG, DISA) **cannot occur on an MS41 M52**, which has a cable throttle,
no DISA on M52 non-TU, and no SMG. Expect only a subset to be reachable.

| Code | Description | System |
|---|---|---|
| 1 | Ignition coil Cyl 2 | Ignition |
| 2 | Ignition coil Cyl 4 | Ignition |
| 3 | Ignition coil Cyl 6 | Ignition |
| 5 | Fuel injector Cyl 2 | Fuel Injectors |
| 6 | Fuel injector Cyl 1 | Fuel Injectors |
| 8 | Air Flow Meter (HFM) | Air Intake |
| 10 | Coolant Temperature Sensor | Temperature |
| 11 | Tank Pressure Sensor / Radiator Outlet Temp | Emissions |
| 12 | TPS or Plausibility - Max Coolant Temp | Throttle |
| 13 | Plausibility - Radiator Outlet Temp | Temperature |
| 14 | Intake Air Temperature Sensor | Temperature |
| 15 | Plausibility - Cut Out Time | ECU Internal |
| 16 | AirCon Compressor PWM / Intake Air Temp | A/C |
| 17 | Plausibility - Engine Coolant Temp | Temperature |
| 18 | EWS Signal or Camshaft Sensor | Immobiliser |
| 19 | VANOS Inlet/Exhaust Valve Activation | VANOS |
| 20 | CHECK ENGINE Light Failure | ECU Internal |
| 21 | VANOS Electrical Fault or Inlet Valve | VANOS |
| 22 | Fuel Injector Cyl 3 | Fuel Injectors |
| 23 | Fuel Injector Cyl 6 | Fuel Injectors |
| 24 | Fuel Injector Cyl 4 | Fuel Injectors |
| 25 | Lambda Sensor Heater Bank 1 | Lambda / Fueling |
| 27 | Idle Control Valve Malfunction | Idle Control |
| 29 | Ignition Coil Cyl 1 | Ignition |
| 30 | Ignition Coil Cyl 3 | Ignition |
| 31 | Ignition Coil Cyl 5 | Ignition |
| 33 | Fuel Injector Cyl 5 | Fuel Injectors |
| 35 | Aux. Air Injection System Relay | Emissions |
| 36 | DME Main Relay | Power Supply |
| 37 | DME Main Relay Delay | Power Supply |
| 38 | Clutch Switch - Plausibility | Input Signals |
| 39 | Brake Light Switch / Test Switch | Input Signals |
| 40 | Brake Light Switch / Pedal Signal | Input Signals |
| 42 | Multi Function Steering Wheel - Plausibility | Communication |
| 43 | Multi Function Steering Wheel Button | Communication |
| 45 | Multi Function Steering Wheel Port | Communication |
| 46 | Fuel-Level Reserve-Lamp Signal | Fuel System |
| 47 | Temp Sensor Downstream Pre-Cat | Temperature |
| 48 | DME Control Unit - Self Test 1 | ECU Internal |
| 49 | DME Control Unit | ECU Internal |
| 50 | EVAP Control Valve | Emissions |
| 51 | Shut-off Valve Charcoal Filter | Emissions |
| 52 | Solenoid Valve - Exhaust Flap | Emissions |
| 53 | Idle Speed Actuator | Idle Control |
| 55 | Lambda Sensor Heater Bank 2 | Lambda / Fueling |
| 56 | Ignition Current Feedback Resistor Open | Ignition |
| 57 | Knock Sensor Bank 1 | Knock Control |
| 58 | DME Control Unit - Self Test 2 | ECU Internal |
| 59 | Knock Sensor Bank 2 | Knock Control |
| 61 | Lambda Sensor Heater Bank 2 Post Cat | Lambda / Fueling |
| 62 | Aux. Air Injection Switching Valve | Emissions |
| 63 | DME Control Unit / Ambient Temp via CAN | ECU Internal |
| 64 | Plausibility - Ambient Temperature | Temperature |
| 65 | Camshaft Position Sensor | Crank/Cam |
| 66 | DME Control Unit | ECU Internal |
| 67 | DME Control Unit | ECU Internal |
| 68 | Tank Venting Valve | Emissions |
| 69 | Fuel Pump Relay | Fuel System |
| 70 | DME Control Unit | ECU Internal |
| 71 | DME Control Unit | ECU Internal |
| 72 | DME Control Unit | ECU Internal |
| 74 | AirCon Compressor Relay | A/C |
| 75 | Lambda Sensor Voltage Bank 1 | Lambda / Fueling |
| 76 | Lambda Sensor Voltage Bank 2 | Lambda / Fueling |
| 77 | Lambda Sensor Voltage Bank 1 Post Cat | Lambda / Fueling |
| 78 | Lambda Sensor Voltage Bank 2 Post Cat | Lambda / Fueling |
| 79 | Lambda Sensor Heater Bank 1 Post Cat | Lambda / Fueling |
| 80 | ABS/ASC Interface | Communication |
| 81 | MSR Signal - Active Too Long | Communication |
| 82 | ABS/ASC Interface - Advance Adjustment | Communication |
| 83 | Crankshaft Sensor | Crank/Cam |
| 90 | Exhaust Temp Pre Cat Bank 1 | Temperature |
| 91 | Exhaust Temp Pre Cat Bank 2 | Temperature |
| 92 | Exhaust Temp Post Cat Bank 1 | Temperature |
| 93 | Exhaust Temp Post Cat Bank 2 | Temperature |
| 94 | Auxiliary Air - Mass Flow Sensor | Emissions |
| 95 | Auxiliary Air Valve or Hose Blocked | Emissions |
| 96 | Auxiliary Air Pump Function | Emissions |
| 97 | Auxiliary Air - Flow Rate Too Low | Emissions |
| 98 | Auxiliary Air - Flow Rate Too High | Emissions |
| 99 | Auxiliary Air Valve Jammed Open | Emissions |
| 100 | DME Control Unit - Self-Test Failed | ECU Internal |
| 103 | VANOS Error - Inlet Camshaft | VANOS |
| 104 | VANOS Error - Exhaust Camshaft | VANOS |
| 105 | VANOS Error - Position Inlet Camshaft | VANOS |
| 106 | VANOS Error - Position Exhaust Camshaft | VANOS |
| 109 | Throttle Valve Plausibility | Throttle |
| 110 | Pedal Sensor Value Potentiometer 1 | Throttle |
| 111 | Pedal Sensor Value Potentiometer 2 | Throttle |
| 112 | TPS Potentiometer 1 | Throttle |
| 113 | TPS Potentiometer 2 | Throttle |
| 114 | Throttle Valve Final Stage | Throttle |
| 115 | Reference Voltage Regulator 1 | ECU Internal |
| 116 | Reference Voltage Regulator 2 | ECU Internal |
| 117 | Plausibility - Pedal Position Sensor 1/2 | Throttle |
| 118 | Plausibility - TPS 1/2 | Throttle |
| 119 | Throttle Valve Sensor Mechanical Error | Throttle |
| 120 | Plausibility Pedal Sensor or TPS | Throttle |
| 122 | Engine Oil Temperature | Temperature |
| 123 | Map Cooling Thermostat Control | Cooling |
| 124 | Activation DISA Solenoid | Air Intake |
| 125 | Activation Electric Fan | Cooling |
| 126 | Activation Tank Leak Pump Solenoid | Emissions |
| 127 | Activation Pump Solenoid | Emissions |
| 128 | DME/EWS Communication | Immobiliser |
| 129 | CAN Signal SMG 1 | Communication |
| 130 | CAN Signal ASC - Timeout | Communication |
| 131 | CAN Signal Instrument Cluster - Timeout | Communication |
| 132 | CAN Signal Instrument Cluster - Timeout | Communication |
| 133 | CAN Signal ASC - Timeout | Communication |
| 134 | SMG Intervention - Plausibility | Communication |
| 135 | Throttle Valve Re-Adaptation Required | Throttle |
| 136 | Throttle Valve Spring Test Failed | Throttle |
| 137 | CAN Signal - Steering Angle Sensor | Communication |
| 139 | CAN Signal - Tank Level Sensor | Communication |
| 140 | Tank Leak Pump Solenoid Reed Switch | Emissions |
| 141 | Tank Leak Pump Reed Switch Stuck | Emissions |
| 142 | Tank Leak Pump Reed Switch Open / DMTL | Emissions |
| 143 | Tank Ventilation / Leakage | Emissions |
| 144 | Fuel System Large Leak | Emissions |
| 145 | Fuel System Small Leak | Emissions |
| 146 | EVAP Small Leak | Emissions |
| 147 | Pedal Position Sensor Supply Channel 1 | Throttle |
| 149 | Air Flow Sensor or Pedal Sensor Mismatch | Air Intake |
| 150 | Lambda Post Cat Bank 1 Max Limit | Lambda / Fueling |
| 151 | Lambda Post Cat Bank 2 Max Limit | Lambda / Fueling |
| 152 | Lambda Post Cat Bank 1 Min Limit | Lambda / Fueling |
| 153 | Lambda Pre Cat Bank 2 Max Limit | Lambda / Fueling |
| 154 | Lambda Pre Cat Bank 2 Min Limit | Lambda / Fueling |
| 155 | Lambda Pre Cat Bank 2 No Signal | Lambda / Fueling |
| 156 | Lambda Pre Cat Bank 1 No Signal | Lambda / Fueling |
| 157 | Lambda Post Cat Bank 1 Min Limit | Lambda / Fueling |
| 159 | Lambda Post Cat Bank 2 Max Limit | Lambda / Fueling |
| 160 | Lambda Post Cat Bank 2 / Throttle Stuck | Lambda / Fueling |
| 161 | Throttle Valve Stuck | Throttle |
| 162 | Throttle Valve Control Deviation | Throttle |
| 168 | Pedal Position Sensor Pot Supply 1 | Throttle |
| 169 | Throttle Valve Output Stage Cutoff | Throttle |
| 170 | DME Control Unit - Self Test Failed | ECU Internal |
| 171 | Plausibility - Throttle Valve | Throttle |
| 172 | Pedal Sensor Potentiometer 1/2 Short | Throttle |
| 173 | TPS Potentiometer 1/2 Short Circuit | Throttle |
| 174 | Throttle Valve Potentiometer 1/2 Adaptation | Throttle |
| 175 | Pedal Sensor 1 Adaptation | Throttle |
| 176 | Pedal Sensor 2 Adaptation | Throttle |
| 186 | Voltage Post Cat Bank 1 | Lambda / Fueling |
| 187 | Voltage Post Cat Bank 2 | Lambda / Fueling |
| 188 | Voltage Pre Cat Bank 1 | Lambda / Fueling |
| 189 | Voltage Pre Cat Bank 2 | Lambda / Fueling |
| 190 | EVAP Reed Switch Open | Emissions |
| 191 | EVAP Reed Switch Closed | Emissions |
| 192 | EVAP Reed Switch Open | Emissions |
| 193 | EVAP Check Hoses | Emissions |
| 194 | EVAP Large Leak | Emissions |
| 195 | EVAP Small Leak | Emissions |
| 196 | EVAP Electrical Valve / Barometric Pressure | Emissions |
| 197 | EVAP Barometric Pressure Sensor | Emissions |
| 198 | Cat Efficiency during Start Bank 1 | Catalyst |
| 199 | Cat Efficiency during Start Bank 2 | Catalyst |
| 200 | Lambda Regulation Bank 1 Pre Cat | Lambda / Fueling |
| 201 | Lambda Regulation Bank 2 Pre Cat | Lambda / Fueling |
| 202 | Lambda Regulation Bank 1 Post Cat | Lambda / Fueling |
| 203 | Lambda Regulation Bank 2 Post Cat | Lambda / Fueling |
| 204 | Idle Control System - Idle Speed Not Plausible | Idle Control |
| 208 | EWS RPM Signal Error | Immobiliser |
| 209 | EWS Message Error | Immobiliser |
| 210 | Ignition Feedback Resistor (ZSR) | Ignition |
| 211 | Idle Speed Actuator - Mechanical | Idle Control |
| 212 | VANOS Bank 1 - Mechanical | VANOS |
| 214 | Vehicle Speed Signal (VSS) | Speed |
| 215 | Lambda Sensor Bank 1 | Lambda / Fueling |
| 216 | Lambda Sensor Bank 2 | Lambda / Fueling |
| 217 | CAN Bus Error - EGS Signal Not Present | Communication |
| 218 | CAN Module Warning | Communication |
| 219 | CAN Module Offline | Communication |
| 220 | Lambda Voltage Range Bank 1 Sensor 1 | Lambda / Fueling |
| 221 | Lambda Voltage Range Bank 2 Sensor 1 | Lambda / Fueling |
| 222 | Low Coolant Temp / Lambda Sensor Control | Temperature |
| 223 | Lambda Sensor Switching Bank 1 Sensor 2 | Lambda / Fueling |
| 224 | Lambda Sensor Switching Bank 2 Sensor 2 | Lambda / Fueling |
| 225 | Cat Efficiency Bank 1 | Catalyst |
| 226 | Cat Efficiency Bank 2 | Catalyst |
| 227 | Mixture Deviation Bank 1 | Lambda / Fueling |
| 228 | Mixture Deviation Bank 2 | Lambda / Fueling |
| 229 | Lambda Sensor Switching Bank 1 | Lambda / Fueling |
| 230 | Lambda Sensor Switching Bank 2 | Lambda / Fueling |
| 231 | Lambda Sensor Switching Bank 1 Pre Cat | Lambda / Fueling |
| 232 | Lambda Sensor Switching Bank 2 Pre Cat | Lambda / Fueling |
| 233 | Catalytic Converter Overall Efficiency Bank 1 | Catalyst |
| 234 | Catalytic Converter Overall Efficiency Bank 2 | Catalyst |
| 235 | Lambda Heater Bank 1 Post Cat | Lambda / Fueling |
| 236 | Lambda Heater Bank 2 Post Cat | Lambda / Fueling |
| 238 | Misfire Cyl 1 | Ignition |
| 239 | Misfire Cyl 2 | Ignition |
| 240 | Misfire Cyl 3 | Ignition |
| 241 | Misfire Cyl 4 | Ignition |
| 242 | Misfire Cyl 5 | Ignition |
| 243 | Misfire Cyl 6 | Ignition |
| 244 | Crankshaft Interval Timing | Crank/Cam |
| 245 | Aux Air Injection System Bank 1 | Emissions |
| 246 | Aux Air Injection System Bank 2 | Emissions |
| 247 | Aux Air Injection System - Incorrect Flow | Emissions |
| 248 | Pre Cat Converter Efficiency Bank 1 | Catalyst |
| 249 | Pre Cat Converter Efficiency Bank 2 | Catalyst |
| 250 | Tank Venting Valve Function | Emissions |
| 251 | Tank Ventilation Diagnosis Error | Emissions |
| 252 | Tank Ventilation System Vacuum | Emissions |
| 253 | Charcoal Filter Shut-off Valve Stuck Shut | Emissions |
| 254 | Tank Ventilation System Large Air Leak | Emissions |
| 255 | Tank Ventilation System Valve Stuck Open | Emissions |

(Codes 4, 7, 9, 26, 28, 32, 34, 41, 44, 54, 60, 73, 84–89, 101, 102, 107, 108, 121, 138, 148,
158, 163–167, 177–185, 205–207, 213, 237 are **unassigned** in this table — report them as
"unknown fault code N" rather than guessing.)

### 4.5 Mapping internal codes to OBD-II P-codes

ms4x's `Diagnostic Trouble Code Translation` page (S3) documents the firmware's own mapping via
`c_dtc_<name>_x` calibration constants — but it is keyed by **symbolic DTC name**
(`c_dtc_lam_stop_1` → P0171/P0172/P1314, `c_dtc_maf` → P0102/P0103, `c_dtc_mis_0` →
P0301/P0313/P1342/P1343, etc.), **not** by the numeric DS2 code. It is an MS4x-family table and
is not aligned to the numeric table in §4.4. To use it you would need the firmware's
name→number ordering, which is not published. **Treat §4.4 and S3 as two separate, unjoined
tables.** [high — this is a real gap, not an oversight]

---

## 5. OBD-II side (cross-check path)

- **MS41.1 and MS41.2 are OBD-II compliant** (US-market 1996+). MS41.0 is the Euro variant and
  BMW did **not** activate the OBD-II P-code layer on it — "the OBD2 P codes fault protocol was
  not activated in European markets on this group, as it was not required by law at that time".
  [medium — community consensus; see also the `c_dtc_*_x` translation-constant mechanism on S3,
  which implies the mapping is calibration-resident and can be absent]
- Transport: **ISO 9141-2**, K-line on OBD-II connector **pin 7**, 10.4 kbaud, 5-baud slow init,
  target address `0x33`. Note DS2 shares the same physical K-line at 9600 8E1 — you must pick
  one protocol per session and the two are not interleavable.
- **Wiring gotcha** (S6, [high]): many "INPA K+DCAN" cables leave OBD pins 7 and 8 unbridged
  because on E90 pin 8 was reassigned. "On the older platforms pin 7 and 8 are both used for
  K-Line communication." If DS2 or OBD-II won't connect on an E36, check/short pins 7–8.
- E36 also has the **20-pin round engine-bay connector**; DS2 is available there too.
- Standard PIDs expected to work on an MS41.1/.2 (Mode 01): `0x00` supported-PID bitmap,
  `0x01` monitor status, `0x03` fuel system status, `0x04` calculated load, `0x05` ECT,
  `0x06/0x07` STFT/LTFT bank 1, `0x08/0x09` STFT/LTFT bank 2, `0x0B` MAP (likely unsupported —
  MS41 is MAF-based), `0x0C` RPM, `0x0D` VSS, `0x0E` timing advance, `0x0F` IAT, `0x10` MAF,
  `0x11` throttle, `0x13/0x14-0x1B` O2 sensors, `0x1F` run time. Modes 02 (freeze frame),
  03/04/07 (DTCs) are required by the standard. **[low — I could not find an MS41-specific
  supported-PID capture; query PID `0x00`/`0x20`/`0x40` at runtime and trust the bitmap rather
  than this list.]**
- Value of this path: an independent sanity check on your DS2 scaling constants
  (RPM, ECT, IAT, MAF, timing advance, STFT/LTFT all exist on both sides). Highly recommended
  as a one-time validation step.

---

## 6. ⚠️ WRITE operations

**Everything in this section modifies ECU state. Gate behind an explicit `--write` /
confirmation flag.**

### 6.1 Clear fault memory — cmd `0x05`
`12 04 05 <xor>` → ACK. No arguments. [high]

### 6.2 Reset adaptations — cmd `0x43`

Frame: `12 <len> 43 <sub1> [<sub2>] <xor>`. ECU replies with an `A0` ACK and empty payload.

BimmerStein sub-byte values [medium, S10]:

| sub1 | sub2 | Effect |
|---|---|---|
| `0xFF` | `0xFF` | Clear **all** adaptations |
| `0xFF` | *(omitted)* | Clear all — **MS41.0 only sends a single sub-byte** |
| `0x01` | `0x00` | Knock adaptation |
| `0x02` | `0x00` | Idle adaptation |
| `0x04` | `0x00` | Lambda / fuel-trim adaptation |
| `0x08` | `0x00` | Throttle adaptation |

RomRaider implements the same command as a **16-bit bitmask** (`constructEcuResetRequest`
packs an int into 2 bytes), with these checkbox bits [high, S9 `DS2ResetPanel.java` +
`DS2ResetPanel.properties`]:

| Mask | Label |
|---|---|
| `0x0100` | Knock Adaptations |
| `0x0200` | Idle Speed Adaptations |
| `0x0400` | Lambda Adaptations |
| `0x0800` | Throttle Adaptations |
| `0x1000` | Altitude Correction |
| `0x2000` | Undefined Adaptation |
| `0x4000` | Undefined Adaptation |
| `0x8000` | Undefined Adaptation |
| `0x0001` | Undefined Adaptation |
| `0x0002` | External Load History (M3 only) |
| `0x0004` | Undefined Adaptation (MS43 only) |
| `0x0008` | Undefined Adaptation (MS43 only) |

**The two sources agree**: RomRaider's high byte (`0x0100` knock, `0x0200` idle, `0x0400`
lambda, `0x0800` throttle) is exactly BimmerStein's `sub1` = `0x01/0x02/0x04/0x08` with
`sub2` = `0x00`. [high — two independent confirmations] This also newly identifies
`sub1=0x10, sub2=0x00` as **altitude correction**.
RomRaider's panel tooltip: *"Unsupported items are ignored by the ECU if selected."*

### 6.3 Component activation / actuator test
**Not documented in any accessible source.** EDIABAS MS41 PRGs contain `STEUERN_*` jobs
(German *steuern* = to control/actuate) which would be the activation path, but no trace of the
serial encoding was published in S7, S9, S10, or on the ms4x wiki. RomRaider does not implement
it. **Open question — see §7.**

### 6.4 Things explicitly NOT to touch from a diagnostics CLI
`0x07` FLASH_OP (erase/program), `0x90` seed/key unlock, `0xA2` prepare. The MS41 bootloader
region is **one-time programmable in normal operation** — "once a byte has been changed from FF
to another value, it is not changeable again" (S1). Writing wrong-variant software bricks the
ECU: "flashing MS41.2 software to a MS41.1 will result in a bricked ECU … only flash MS41.0
software onto an MS41.0 DME" (S11). [high]

---

## 7. Conflicts and open questions

### Conflicts

1. **Coolant-temperature scaling differs by access path.**
   - RAM (`0xDA5A`) and DTC freeze frame: `°C = 0.747 × raw − 48` (rising raw = rising temp).
   - Status group `0x0B 03` data[7]: `°C = 108 − 0.45 × raw` (falling raw = rising temp).
   These are *not* reconcilable as the same byte; they are two different encodings (the group
   read appears to carry a raw/inverted sensor value). **Do not cross-apply.** [high confidence
   that both are individually correct; both are independently derived from data]

2. **ADC volts-per-bit: 0.0193 vs 0.0196.** The single S7 capture gives 0.0193 exactly
   (250 → 4.825 V); the BMW FUMWELTTEXTE table gives 0.0196. Suspect the EDIABAS job applies a
   rounded constant, or the capture's value was itself computed with an offset. Difference is
   1.5 % — irrelevant for display, relevant if you threshold on it. **Prefer the 10-bit form
   `(raw & 0x3FF) × 5/1023` from the logger definition for the RAM ADC addresses, and 0.0196
   for the DS2 ADC-channel command.** [open]

3. **Flash memory map: file order vs DS2 order.** S1 says calibration lives at file
   `0x10000-0x15FFF`. S10 says the live tune partition is DS2 `0x10000-0x15FFF` which maps to
   file `0x14000-0x17FFF` then `0x10000-0x11FFF`, and that low-region DS2↔file translation is
   XOR 0x4000. These cannot both be literally true. For *reading live data over DS2* it does not
   matter (use DS2 addresses as given); it matters if you ever correlate a .bin to live reads.
   [unresolved]

4. **MS41.1 is "M52 OBDII" (S1) but the Alpina B10 3.2 S52B32 is also MS41.1 (S11).** S1's
   one-line variant summary is a simplification. Trust S11's per-ZB table.

5. **ECU-ID namespace mixes HW-NRs and SW-NRs.** `1438068` and `1438137` appear in tooling as
   ECU IDs but in SP-Daten as software numbers. Either the tooling is wrong, or some DMEs report
   their SW number in the ident's first 7 bytes. Needs a live capture to settle. [open]

### Open questions / gaps

1. **The full `0x0B 03` status-record layout is not publicly retrievable.** mrf582 decoded RPM,
   coolant, air temp, vehicle speed, load (mg/stroke), VANOS angle, ignition angle, injection
   time, MAF kg/h, MAF volts and TPS volts from the MS41.2 traces and put them in a Google Sheet
   (S13) — **that sheet now requires sign-in**, and the RomRaider thread attachments (S7/S8) are
   gated behind forum account approval. *Mitigations:* (a) request forum access
   (post in the "BMW MS41 Tuning New Members" thread per S8); (b) obtain the RomRaider DS2
   logger definition XML, which is the machine-readable version of the same data; (c) **just use
   the RAM-read path (§3.6), which is fully documented and does not need any of this.**

2. **Idle speed setpoint / target RPM has no known live address.** Only calibration tables
   (`ip_n_sp_is` family, S1) are documented. Would need a RAM-map search or firmware disassembly.

3. **Component activation (`STEUERN_*`) serial encoding is unknown.** Likely `0x0C` or a `0x0B`
   subfunction. No source found. Would need an INPA/Tool32 trace while running an actuator test.

4. **Cmd `0x0D` STATUS returns 69 bytes; the layout is undocumented.** This might well be the
   "one shot everything" record and is worth capturing early — it's a cheap experiment.

5. **DS2 numeric code → OBD-II P-code join is missing** (§4.5).

6. **ms4x.net's DS2 protocol and "Siemens DTC Data Explained" pages are empty stubs.** If the
   wiki is ever filled in they would supersede several [medium] entries here. Worth re-checking.

7. **Everything keyed to a specific ECU ID in §3.6.2 is single-sourced** (BimmerStein). The
   addresses are plausible and internally consistent (e.g. the three per-variant fuel-trim
   blocks sit at consistent relative offsets: ST→LT is always +0x12, additive→multiplicative is
   always +0x08, B1→B2 is +0x3A for 1429861 and +0xBC for the later programs). Validate the
   first few on the actual car against OBD-II Mode 01 PIDs 06/07 before trusting the rest.

8. **Logging rate on stock MS41 is unmeasured here.** BimmerStein polls the telegram at ~112 ms
   (~9 Hz) and the per-block `0x06` path is slower (one round trip per contiguous block). Budget
   for 2–9 Hz, not the 25–33 Hz quoted for patched MS42/MS43.

### Suggested validation plan for the target car

1. `0x00` ident → confirm ECU ID (expect `1437806`), record all 42 bytes verbatim.
2. Read CAL ID at DS2 `0x1000E` (8 bytes) → confirm the `60` prefix; if a tuner reflashed it the
   prefix should still be `60`.
3. Read program part at `0x2025` and compat IDs at `0x2007`/`0x1000C` → detect a cal/program
   mismatch (a sign of a cross-flashed tune).
4. Read the AIF history → `programming_count > 1` means it's been reflashed.
5. `0x06` read `0xDA2A`..`0xDA64` as one 0x3B-byte block → RPM/MAF/IAT/ECT/VSS/CPV in one shot;
   sanity-check RPM against the tach.
6. Cross-check RPM/ECT/IAT/MAF/timing/STFT/LTFT against OBD-II Mode 01.
7. `0x0D` and `0x0B 03` — capture raw and archive, even if undecoded.
8. Expect skewed trims: a 2.5 L engine on a 2.8 calibration over-fuels, so LTFT should sit
   negative (lean correction) once closed-loop.
