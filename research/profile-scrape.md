# Profile scrape — per-ECU-ID source inventory

Pass date: 2026-10-27. Goal: ship a real profile for every DME variant whose RAM
parameter map is published somewhere, instead of dropping those cars onto the
generic fallback.

Nothing added in this pass is verified. Every parameter carries
`verified = false` and a `source` that names the exact file and line it came
from. Every scraped profile's `description` ends with `(unverified)`, and
`e36 ident` now prints `(unverified profile)` on the profile line when the
matched profile contains zero verified params.

Companion doc: `research/ms41-data.md` (the protocol- and family-level
research this builds on). This file is only about *which ECU ID got which
addresses from where*.

---

## 1. Sources consulted

| # | Source | What it actually contains | Verdict |
|---|---|---|---|
| S-A | `CAATZ/BimmerStein-ECU-Tool`, `logger_definitions/BimmerStein MS41 Logger Definitions.xml` (397 lines, RomRaider logger format, GPL-3.0) | `<ecuparam>` entries, each with one or more `<ecu id="a,b,c">` rows giving an absolute C166 address plus a `<conversion>` (storagetype, endian, expr, units). Covers ECU IDs `1405854, 1406464, SHINDE1, 1429373, 1429861, 1432401, 1437806, 1440176`. | **Primary.** Machine-readable, per-ECU-ID, explicit. |
| S-B | same repo, `ds2.py` L770-795 — `_BATCH_ECU_ADDRS` + `_build_batch_setup` | The MS41 batch-telegram setup frame. 8 per-ECU-ID variable addresses (`tps, lt_b1, lt_b2, st_b1_hi, st_b2_hi, injector_pw, engine_load, battery`) keyed by ECU-ID string, **including two IDs the logger XML does not cover: `1438068` and `1438137`**. The remaining 16 entries are hardcoded in the frame with the comment (L772) that entries 0-4, 6-13 and 18-23 are "shared (same address on every MS41)". | **Primary** for `1438068` / `1438137`, corroborating elsewhere. |
| S-C | same repo, `live_data.py` L50-58 — `_WBO2_INPUT_SOURCES` | MS41-wide 10-bit ADC source table: TPS volts `0xE8DA`, TPS base `0xFAA2`, rear O2 B1 `0xFA96`, rear O2 B2 `0xFA94`, front O2 B2 `0xFA98`, front O2 B1 `0xFA9A`, EVAP pressure `0xF5A8`. **Not keyed by ECU ID** — it is a property of the MS41 ADC block. | Secondary; used, with the non-ECU-scoping stated in each `source` string. |
| S-D | same repo, `ms41.py` L91-97 (`_PROG_ECU_ID_MAP`), `gui.py` L830-840, `transmission_conversion.py` L496-505 | ECU-ID → variant-family lookup tables. No addresses. | Used only to name variants. |
| S-E | `research/ms41-data.md` §1.2 (SP-Daten S11 `Zusbauvorschrift`) | ECU-ID → vehicle application. **No addresses at all.** | Naming/applications only. |

The BimmerStein repo is GPL-3.0; e36cli is GPL-3.0; deriving profile data from
it is fine and the provenance strings name it.

## 2. Per-ECU-ID inventory

Legend: **XML-common** = the 16 channels the logger XML lists for that ECU ID in
a shared `<ecu id="...">` list (RPM, MAF, idle valve, IAT, EVAP duty, coolant,
VSS, ignition advance, knock current, knock global, VANOS, front O2 B1/B2, MAF
volts, engine-state byte, operating-state byte). **ADC extras** = the three
S-C channels used by every shipped profile (TPS volts, rear O2 B1/B2).
**Variant column** = the 8 addresses that move between variants.

| ECU ID | Family | Sources with addresses | Encoded as | Params |
|---|---|---|---|---|
| `1405854` | MS41.0-ish (not in SP-Daten) | S-A: XML-common only | **new** `ms41.0-1405854` | 19 |
| `1406464` | MS41.2 | S-A: full column | existing `ms41.2` (unchanged) | 29 |
| `1427703` | MS41.0 MDS410, early | *none* | **no profile** → generic | — |
| `1429373` | MS41.0 | S-A: XML-common; plus this car's live probe | existing `ms41.0-1429373` (unchanged) | 31 |
| `1429861` | MS41.0 MDS411 | S-A: full column | existing `ms41.0` (match_hw narrowed) | 29 |
| `1432401` | MS41.0 | S-A: XML-common; S-B L786: variant column | **new** `ms41.0-1432401` | 27 |
| `1437804` | MS41.1 | *none* | **no profile** → generic (was wrongly on `ms41.1`) | — |
| `1437806` | MS41.1 | S-A: full column | existing `ms41.1` (match_hw narrowed) | 29 |
| `1438068` | MS41.1 (SW-NR) | S-B L783: variant column; S-B L772+frame: shared entries | **new** `ms41.1-1438068` | 27 |
| `1438137` | MS41.0 (SW-NR) | S-B L788: variant column; S-B L772+frame: shared entries | **new** `ms41.0-1438137` | 27 |
| `1440176` | MS41.0, E36 323ti Compact 6/99+ | S-A: XML-common only | **new** `ms41.0-1440176` | 19 |
| `7505858` | MS41.0, Z3 2.8 Dubai | *none* | **no profile** → generic | — |
| `SHINDE1` | MS41.3 community firmware | S-A: full 1406464-joint column **+ MS41.3-only wideband** | **new** `ms41.3-shinde1` | 39 |

Six new profiles, 158 new parameter definitions, all `verified = false`.

### 2.1 Notes per new profile

**`ms41.0-1405854` / `ms41.0-1440176` (19 params each).** The logger XML names
these two IDs in the shared `<ecu id>` lists for the 16 common channels and
*nowhere else* — in particular `P13` throttle position (`0xE8D0`) does not list
them, nor does any injector-PW / fuel-trim / load / battery entry, nor does
`ds2.py`'s batch table have a row for them. So those are absent rather than
borrowed from `1429861`. Core subset is 7 (the common physics channels); the
other profiles' core sets of 11 include `tps`, `battery` and the short trims,
which these two have no source for.

**`ms41.0-1432401` (27 params).** XML-common + ADC extras + the eight
`_BATCH_ECU_ADDRS['1432401']` addresses. Those eight happen to equal the
`1429861` tuple, but the source lists them under `1432401` in its own right, so
this is a scrape and not an interpolation. Scalings for the eight come from the
logger XML `<conversion>` that owns each address (`BS_INJECTOR_PW`, `E21`,
`E22`, `E2`, `P17`, `P13`), cited per param.

**`ms41.0-1438137` (27 params) / `ms41.1-1438068` (27 params).** Neither ID
appears in the logger XML. Their common block is therefore sourced from
`ds2.py`'s batch setup frame instead — the frame hardcodes those 16 addresses
for *every* key in `_BATCH_ECU_ADDRS`, and L772 states explicitly that those
entries are shared across every MS41. Scalings again from the XML conversion
that owns each address. Caveat recorded in §5.

**`ms41.3-shinde1` (39 params).** The XML lists `SHINDE1` jointly with
`1406464` on every stock channel, so the base map is MS41.2's. It gets its own
profile because MS41.3 adds channels that do not exist on stock MS41.2:
`BS_WB_AFR` `0xE800` and `BS_WB_TARGET` `0xE811` (`x*0.05+8.25` AFR). It also
picks up the O2-heater duties, lambda-regulation flag bytes and the `FD0E`/
`FD10` lambda function words that the XML lists for the `1406464,SHINDE1` pair.
`SHINDE1` was removed from `ms41.2`'s `match_hw` in the same change.

## 3. Encoded vs skipped

### Encoded
- All 16 XML-common channels, for every ID that the XML or `ds2.py` lists.
- The 3 MS41-wide ADC extras (TPS volts, rear O2 B1/B2), matching what the
  pre-existing profiles already ship.
- Per-ID variant columns where a source names them for that ID.
- MS41.3 wideband AFR + AFR target.
- MS41.2/.3 O2 heater duties and lambda flags, for `SHINDE1`.

### Skipped, and why
| Skipped | Why |
|---|---|
| `BS_WB_INPUT` (`0xFA9A`, SHINDE1) | A runtime-selected ADC *pointer* that aliases the front-O2-B1 address already in the profile. Encoding it would be a duplicate address under a second name, and the real source address is only known after reading the `0x133C0` selector. |
| Ignition-cut / launch-control channels at `0x12A65+`, `0x13010+`, `0x13700+`, `0x147E0+` | Flash **calibration** bytes for a third-party patch, not live telemetry, and meaningless on an unpatched ECU. Out of scope for a diagnostic read set. |
| `BS_CUT_*` runtime bits at `0xE847`, `0xFD5A`, `0xFD61`, `0xFDB6`, `0xFD13`, `0xFC3C` | Only meaningful when the BimmerStein cut patch is flashed. Would read garbage on stock firmware. |
| Knock-adaptation table axes (`0x12606`, `0x1239A`, `0x12144`, `0x12388`) | Calibration-side reads, already documented in `ms41-data.md` §3.6.2; not per-sample live params. |
| Knock adaptation block `0xD840` (6 × 0x40 bytes) | 384 bytes — too large for the per-poll read planner, and it is a table, not a scalar. Noted for a future dedicated command. |
| Throttle adaptation `0xE8DE`, TPS base volts `0xFAA2`, EVAP pressure `0xF5A8` | Present in S-C but not shipped by any existing profile either; left out for consistency rather than silently widening every profile in a scrape pass. |
| `1427703`, `1437804`, `7505858` | No source publishes a RAM map. See §4. |
| MS42 / MS43 ECU IDs | See §6. |

## 4. Corrections to existing profiles

This pass found three ECU IDs being matched to profiles whose
*variant-specific* addresses no source attributes to them. Matching is not
free: it means `e36 live` would read `0xED6E` as "long trim B1" on an ECU where
nobody has shown that it is. The honest fallback is `ms41-generic`, whose
common block is correct on every documented MS41.

| ECU ID | Was | Now | Reason |
|---|---|---|---|
| `1440176` | `ms41.0` (full 1429861 column) | `ms41.0-1440176` (common block) | XML lists it for the common channels only |
| `1427703` | `ms41.0` (full 1429861 column) | `ms41-generic` | MDS410 is an *earlier program generation* than MDS411/1429861; no map published |
| `7505858` | `ms41.0` (full 1429861 column) | `ms41-generic` | Z3 2.8 Dubai; appears only in SP-Daten, no map published |
| `1437804` | `ms41.1` (full 1437806 column) | `ms41-generic` | Appears only in SP-Daten (E39 528i '98 w/ DM-TL, Alpina B10 3.2); no map published |
| `SHINDE1` | `ms41.2` | `ms41.3-shinde1` | Same base map, plus MS41.3-only wideband channels |

`--profile ms41.0` / `--profile ms41.1` still force the old behaviour for
anyone who wants to gamble on a sibling's map; `e36 ident` will warn that the
generic fallback was used.

**Judgement call worth re-reading:** `1437804` is the closest of these to being
safe — it is the same MS41.1 generation as `1437806`, differing by the DM-TL
leak pump — and an owner may well decide the trims line up. It is demoted here
because the rule for this pass was "only what a source lists for that exact ECU
ID", applied without exceptions. One live capture from a 1437804 car settles it
and the ID can be folded back into `ms41.1`.

## 5. Conflicts and caveats found

1. **Short-trim representation differs between the two BimmerStein sources.**
   The logger XML gives the full 16-bit short-term trim (`E13`/`E14`, e.g.
   `0xF01E`, `(x-32768)*100/65535` %). `ds2.py`'s batch table instead stores
   **the high byte only**, at `ST_addr + 1`, scaled `(x-128)*100/256` — the
   source cross-checks this itself at L779 (`1406464 st_b1=0xF01F = 0xF01E+1`).
   For `1432401`, `1438137` and `1438068` the high-byte form is the *only*
   sourced form, so those profiles ship params named `stft_b1_hi` / `stft_b2_hi`
   rather than `stft_b1` / `stft_b2`. The distinct names are deliberate: the
   value is a coarser, differently-scaled quantity, and a future reader
   comparing two profiles should notice.

2. **`1438068` and `1438137` are SP-Daten software numbers, not hardware
   numbers** (`1438068DA`, `1438137DA`). BimmerStein's tooling keys on them as
   ECU-ID strings anyway. Either the tool is wrong or some DMEs report their SW
   number in the ident's first seven bytes — unresolved, and already logged as
   `ms41-data.md` §9.5. Profiles for them are cheap and harmless if no car ever
   reports those strings; if one does, the map is ready. This is the weakest
   link in this pass.

3. **`1405854` is recognised by the logger XML but appears in no BMW parts
   table** found so far. Family assignment "MS41.0-ish" is inference from the
   company it keeps in the XML ECU lists; the profile id says `ms41.0-1405854`
   but nothing depends on that guess — only the addresses, which are sourced.

4. **Batch-telegram addresses vs `0x06` RAM reads.** `ds2.py`'s per-ECU table
   describes addresses used inside the `0x0B 01`/`0x0B 00` batch telegram, not
   `0x06` reads. They are the same C166 absolute addresses in the same memory,
   and the XML uses the same values for its `0x06` channels wherever the two
   overlap — but for `1438068`/`1438137` there is no overlap to check against,
   because those IDs exist only in the batch table. Called out because it is the
   one place in this pass where a source is used slightly outside the command
   scheme it documents.

5. **Core-subset size is not uniform.** 11 core params on the full profiles
   (matching the pre-existing ones), 7 on `1405854`/`1440176` — those two have
   no sourced `tps`, `battery` or short-trim address to promote. The perf
   targets in SPEC are stated for the 11-param core; the 7-param core is
   strictly cheaper.

## 6. MS42 / MS43 — deliberately not added

The only MS4x ECU IDs any consulted source names are in
`transmission_conversion.py` L494-503 (`_DME_PROGRAM_FAMILY`), a family lookup
with **no addresses**: MS42 = `7500255`, `7505859`, `7526753`; MS43 =
`4482751`, `7511570`, `7528050`, `7545150`, `7551615`, `7571017`, `7572342`.
`dtc.py` L58 additionally notes its single-byte DTC database is shared across
MS41/MS42/MS43. Of the candidate IDs in the directive, `1429764`, `1430844` and
`7519308` appear **nowhere** in the repo. **No RAM parameter map for any
MS42/MS43 ECU ID was found in any consulted source**, so there is nothing to
encode even if the command scheme matched.

Separately, `ms41-data.md` §3.8 already records that MS4x live logging is a
different animal: the Logger.S project reports up to 33 Hz on MS42/MS43 because
those ECUs take an *extended-logging patch*, which MS41 lacks. The MS4x logging
path is not the MS41 `0x06` RAM read. Per the directive, no MS42/MS43 profiles
are added; if one is ever wanted it needs its own protocol research, not a
profile file.

## 7. Reproducing this scrape

```sh
git clone --depth 1 https://github.com/CAATZ/BimmerStein-ECU-Tool
# addresses:
#   logger_definitions/BimmerStein MS41 Logger Definitions.xml   (all <ecuparam>)
#   ds2.py          L770-795   _BATCH_ECU_ADDRS, _build_batch_setup
#   live_data.py    L50-58     _WBO2_INPUT_SOURCES
```

Line numbers in `source =` strings are against the repo state cloned on
2026-10-27. If upstream moves, the `<ecuparam id>` / symbol names in the same
string still locate the data.

Validation: `tests/test_ms41.py` loads and validates every shipped profile
(schema, formula compilation over the raw range, core-subset size, read-planner
coverage), asserts each profile is matched by exactly the ECU IDs it claims,
asserts no ECU ID is claimed twice, asserts every scraped profile's description
ends with `(unverified)` and contains zero verified params, and asserts the
unsourced IDs of §4 land on the generic fallback.
