# E36 Service-Interval (SIA) Reset & Cluster/Body-Module DS2 — Research Notes

Target car: 1996 Euro E36, M52, MS41.0 DME, KKL cable, DS2 to DME @ 0x12 already working.
Researched 2026-10-25. Every fact carries a source URL and a confidence tag.

**Reading rule for this doc:** a lot of the public material conflates E36 with E46/E39.
Facts below are tagged `[E36]`, `[E39/E38]`, `[E46]` or `[generic DS2]`. Nothing tagged
`[E46]` should be assumed to transfer to the E36 cluster.

---

## 0. TL;DR of the two questions

- Pin-7 grounding is the **documented, universally reproduced, zero-risk** way to reset the
  E36 SIA. Confidence: high.
- A DS2 `SIA_RESET` job **does exist in BMW's own E36 cluster SGBD** (`KOMBI36.prg`,
  `KOMBI361.prg`), so the cluster firmware genuinely implements a diagnostic reset.
  Confidence: high. **But the raw DS2 request bytes are not public anywhere I could find**,
  and on a Euro E36 the cluster normally needs an ADS interface rather than a plain KKL
  cable. Confidence that we can implement it blind: low.
- Go/no-go section at the end.

---

## 1. SIA reset on E36

### 1a. The 20-pin round connector, pin-7-to-ground method `[E36]`

**What the pin is.** On the BMW round 20-pin diagnostic connector, **pin 7 = "Oil service
and Inspection reset"**, **pin 19 = GND**, pin 20 = K-line (TXD), pin 15 = L-line (RXD),
pin 16 = KL.15 (+12 V switched), pin 14 = battery +12 V, pin 1 = TD (engine speed),
pin 18 = PGSP programming line. Only ~9 of the 20 positions are populated.
Source: https://pinoutguide.com/CarElectronics/car_diag_pinout.shtml and
https://www.bmwclubgoldcoast.com/home/tech-tips/reset-service-indicator-round-plug
Confidence: **high** (two independent sources agree on pin 7 / pin 19).

**Connector location on E36:** engine bay, right-hand side near the strut tower / brake
fluid reservoir, under a screw-on black cap. (Some write-ups say "left strut tower" — it is
the passenger side on LHD, which is why sources disagree.)
Sources: https://bimmertips.com/reset-e36-oil-service-inspection-light-how-to/ ,
https://www.department69.com/articles/how-to-reset-bmw-e36-oil-service-light-with-a-paperclip
Confidence: high (location), medium (which side, is just LHD/RHD confusion).

**Procedure (consensus form):**
1. Ignition OFF, unscrew the cap on the 20-pin connector.
2. Turn ignition to **position II (KL.15 on, engine NOT running)**. The SI LEDs light.
3. Insert the jumper into **pin 7 first**, then to **pin 19 (ground)**.
4. Hold for the interval (below).
5. Remove the jumper, ignition off, ignition on again to verify (5 green bars, yellow/red
   cleared).
Sources: https://www.department69.com/articles/how-to-reset-bmw-e36-oil-service-light-with-a-paperclip ,
https://bimmertips.com/reset-e36-oil-service-inspection-light-how-to/
Confidence: **high** for the shape of the procedure.

**Timings — the sources genuinely disagree.** This matters, so here is the raw spread:

| Source | Oil service | Inspection / brake-fluid |
|---|---|---|
| technicae.wordpress.com (DE) | 3 s | 12 s |
| e36-wartung.e36-page.net (DE) | 3 s | 12 s |
| steemit (peterschroeter) | 3.25 s = 7 LED flashes | 11 s = 23 LED flashes |
| bmwclubgoldcoast.com | ~4 s | 10 s |
| bimmertips.com | ~4 s | (not differentiated) |
| department69.com | 3–5 s | (not covered) |
| search-surfaced variant | ~3 s | ~9 s |

Sources: https://technicae.wordpress.com/2012/05/09/bmw-e36-olservice-und-inspektionsanzeige-zurucksetzen/ ,
https://e36-wartung.e36-page.net/wartung-e36-serviceanzeige.html ,
https://steemit.com/cars/@peterschroeter/diy-reset-the-service-interval-display-notification-on-any-bmw-built-between-1982-1999-e30-e46-e39-e36-etc ,
https://www.bmwclubgoldcoast.com/home/tech-tips/reset-service-indicator-round-plug

Confidence: **medium-high** that the real windows are roughly "≈3–5 s → oil service" and
"≈10–12 s → inspection"; **low** on any single exact number. The steemit author explicitly
says "rough estimation works, it doesn't have to be 3.25 seconds". The LED-flash count is
the reliable feedback channel: **count flashes, not seconds** — 7 flashes = oil, 23 flashes
= inspection (steemit, confidence medium — only one source gives flash counts).

**When the reset commits:** steemit says "on older models the system resets after the time
interval, on newer models it resets upon removal of the wire from pin #7". Practically: the
reset lands when you pull the jumper. Confidence: medium.

**Current-limiting resistor.** Several guides recommend putting a **470 Ω** resistor inline
"to prevent damage to the electronics"; others use bare wire. Mentioned in the German
reset write-ups and in DIY reset-tool builds (banana plug + 470 Ω + alligator clip).
Sources: search-surfaced text on https://www.oliverhaas.net/tag/service-intervall-zurucksetzen-bmw-e36
and https://www.unofficialbmw.com/e36/electrical/e36_reset_service_lights.html (site was
unreachable over HTTPS during research; content only seen via search index).
Confidence: **medium** that a resistor is advisable, **low** that 470 Ω specifically is the
BMW-blessed value. Harmless either way.

**Which model years / is the 1996 E36 "pin-7 only"?**
- The method is reported to work for the whole SI-board era, roughly **1982–1999**:
  E30, E34, E36, E39, E46 (early), Z3. Source: steemit article title/body. Confidence: medium.
- bimmertips states explicitly: *"The below procedures works for all BMW E36 3 series models
  both OBDI and OBDII models."* — i.e. a 1996 Euro E36 is in scope.
  Source: https://bimmertips.com/reset-e36-oil-service-inspection-light-how-to/ Confidence: high.
- **The "hold the trip-odometer button with ignition to position 1 until RST appears" method
  is NOT an E36 method.** That is E46/E39/E38-class clusters with an OBC reset mode. Several
  search results blend the two. On an E36 the SI display is the five LED bars plus
  OIL SERVICE / INSPECTION legends and there is no RST menu.
  Confidence: **high** that it does not apply to E36 (the E36 cluster SGBD has no such job
  and no E36-specific source describes it); the garagediag source code even documents the
  button method as the "always-working manual fallback" **for its E39**, not for an E36.
  Source: https://github.com/tooming/garagediag (`ds2_diag.py`, `DS2.sia_reset` docstring).
- So: **for a 1996 E36, pin-7 grounding is the only method that is publicly documented and
  independently reproduced.** INPA-era commentary on the forums says plainly that you cannot
  reset E36 service interval with INPA/DIS and that BMW's own service tool is "basically the
  same as the paperclip/wire trick with an automatic timer".
  Source: search-surfaced forum consensus, e.g. https://www.bimmerfest.com/threads/how-do-i-do-a-oil-reset-with-inpa.1372603/
  Confidence: **medium** (forum consensus, not fetched in full; and see §1b which shows the
  SGBD job *does* exist, so "INPA can't" is probably about the INPA menu scripts, not about
  the cluster's capability).

### 1b. Does the E36 cluster support SIA reset over DS2? `[E36]` — YES, at the job level

This is the strongest new finding. BMW's own EDIABAS description files for the **E36**
cluster are public in documented form:

- `KOMBI36.prg` — ECU string: **"Kombi E36"**, 17 jobs, 5 tables.
- `KOMBI361.prg` — ECU string: **"Kombi E36"**, 18 jobs (adds `EEPROM_LESEN`).
- `KOMBI36C.prg` — ECU string: **"KOMBI E36C"**, comment **"CAN-Kombi fuer E36/5/7"**
  (i.e. E36 Compact / Z3), 39 jobs — a different, much richer cluster.

Source: https://github.com/emdzej/ediabasx-docs-sgbd → `docs/sgbd/KOMBI36.md`,
`KOMBI361.md`, `KOMBI36C.md`; browsable at https://emdzej.github.io/ediabasx-docs-sgbd/
Confidence: **high** (these are machine-extracted from the real .prg files).

`KOMBI36.prg` job list (the relevant ones):

```
IDENT              Auslesen der Identifikationsdaten
FS_LESEN           read fault memory
FS_LOESCHEN        clear fault memory
DIAGNOSE_ENDE      end diagnosis
GWSZ_RESET         *** reset the total odometer *** (no arguments!)
SIA_RESET          Ruecksetzen der Service-Intervall-Anzeige   (ARG1..ARG4)
FG_NR_LESEN        read VIN
CODIERUNG_LESEN    read full cluster coding (huge result set)
STATUS_LESEN       read live statuses
SPEICHER_LESEN     read memory (ANZAHL 1..16, ADRESSE_HIGH, ADRESSE_LOW)
STEUERN_ANALOG     drive gauges (TACHO/DZM/KVA/TANK/TEMP/OELTEMP/IK_LCD)
STEUERN_TACHO_A    drive speedo 6..300 km/h
SELBSTTEST / STEUERN_SELBSTTEST
STEUERN_DIGITAL    drive GONG_T3/TANKRES/UEBERTEMP/BVA/GURT/EGS/AKUSTIK
```

`SIA_RESET` takes 1–4 string arguments, each one of "Oel/Weg/AG-Oel oder Zeit - Reset",
and returns `JOB_STATUS` ∈ {OKAY, ERROR_NACK, ERROR_PARAMETER}.

**The selector byte table is public** — `KOMBI36.prg` table `SIARESET`:

| SELECTOR | byte |
|---|---|
| `OEL_RESET` | 0x01 |
| `WEG_RESET` (distance/inspection) | 0x02 |
| `AG_OEL_RESET` (auto-gearbox oil) | 0x03 |
| `ZEIT_RESET` (time) | 0x04 |
| unbekannt | 0x00 |

`KOMBI361.prg` table `SIARESET`: `OEL_RESET` 0x01, `WEG_RESET` 0x02, `ZEIT_RESET` 0x04,
unbekannt 0x00 (no AG-oil entry).

`KOMBI36C.prg` (Compact/Z3 CAN cluster) has a **merged** job `SIA_GWSZ_RESET` whose table is
a **bitmask in one byte**: `OEL_RESET` 0x01, `INSPEKTION_RESET` 0x02, `ZEIT_RESET` 0x04,
**`GWSZ_RESET` 0x08**, `FEHLER` 0x00 — i.e. on that cluster the odometer reset lives in the
same byte as the oil reset, one bit away.

Confidence: **high** (verbatim from the SGBD doc tables).

**What is still missing: the DS2 opcode.** The published SGBD docs are job-level: they list
jobs, arguments, results and lookup tables, but not the raw request telegram. I found **no
public source** giving the DS2 request bytes for `SIA_RESET` on any BMW cluster:

- garagediag (the closest open-source prior art, written against an E39) ships a stub:
  `DS2.sia_reset()` sends `0x80 [0x31, kind]` and its own docstring says —
  *"EXPERIMENTAL: selector values are documented (KOMBI39 SGBD SIARESET table: 0x01 oil,
  0x02 distance, 0x04 time) but the DS2 command byte is not public; **0x31 was rejected 0xFF
  (invalid command)** on this car. Do NOT probe blindly — the neighbouring command space
  includes cluster coding writes."*
  Its `operations.json` lists `oil_service_reset` with `"request": null`, `implemented:false`,
  `tested:false`. Its `ADAPTATIONS.md` says: *"| IKE | 0x80 | SIA_RESET (service interval;
  command byte still unknown)"*.
  Source: https://github.com/tooming/garagediag (`ds2_diag.py`, `operations.json`,
  `ADAPTATIONS.md`, `actuators.py`). Confidence: **high** (read the source directly).
  Note this is `[E39/E38]` evidence — but it is evidence that the opcode is unpublished
  *in general*, not just for E36.
- Other open-source DS2 work I checked — https://github.com/handmade0octopus/ds2 (Arduino
  DS2 lib), https://github.com/opetany93/ds2-protocol (Rust), https://github.com/oleavr/bmw-coding,
  https://github.com/tomicooler/bmwe46oil — implement framing / DME live data / coding reads.
  **None implements a cluster service reset.** Confidence: high for the first three (cloned
  and grepped); medium for bmwe46oil (read README + file list; it is an oil *temperature*
  reader, not an oil *service* reset, despite the name's resemblance).

**Generic DS2 opcodes that ARE public** `[generic DS2]` — frame is
`[addr][total_len][data…][XOR]`, 9600 8E1, response status 0xA0 = OK, 0xA1 busy,
0xA2 invalid parameter, 0xFF invalid command:

| opcode | meaning |
|---|---|
| 0x00 | IDENT |
| 0x04 | read fault memory |
| 0x05 | clear fault memory |
| 0x06 | end diagnosis |
| 0x07 | write coding |
| 0x08 | read coding |
| 0x0B `<sub>` | status / live block |
| 0x22 `<id> <val>` | actuator control (DME, from emdzej/j2534 MS43) |
| 0x43 `<mask>` | selective adaptation erase (DME) |

Sources: https://github.com/tooming/garagediag (`ds2_diag.py`, `operations.json`),
http://markgardnergibson.com/BMW/protocol.html (frame format; page was unreachable at fetch
time, format corroborated by garagediag and by search index).
Confidence: high for 0x00/0x04/0x05/0x0B/0x07/0x08; medium for 0x22/0x43 (DME-specific).

**Speculation, flagged as such:** the E36 `SIA_RESET` request is *probably* a short write of
the form `80 05 <opcode> <selector> <xor>` with `<selector>` from the table above, and
multi-argument calls probably send several such telegrams or one with up to 4 selector bytes
(the job accepts ARG1..ARG4). The opcode is unknown. **This is a guess and must not be
brute-forced** — see §1c.

### 1c. Risk profile of writing to the E36 cluster `[E36]`

**KNOWN risks (from BMW's own job list, high confidence):**

1. **`GWSZ_RESET` — "Ruecksetzen des Gesamtwegstreckenzaehlers" — resets the total odometer,
   and in `KOMBI36.prg` it takes _no arguments at all_.** A single stray opcode byte sent to
   0x80 can therefore, in principle, zero the mileage. That is irreversible in the cluster
   without EEPROM surgery, and odometer tampering is a criminal offence in most
   jurisdictions. Source: `docs/sgbd/KOMBI36.md` in
   https://github.com/emdzej/ediabasx-docs-sgbd . Confidence: **high**.
2. On the sibling `KOMBI36C` cluster the odometer reset is literally **bit 3 of the same
   selector byte** as the oil reset (0x08 vs 0x01). If the plain E36 cluster shares any of
   that firmware lineage, a wrong *selector* (not just a wrong opcode) is dangerous.
   Confidence: high that the 36C table says this; **low/medium** that it transfers to
   `KOMBI36`'s own `SIA_RESET` (which uses 0x01/0x02/0x03/0x04 as an enum, not a bitmask —
   evidence *against* transfer).
3. The cluster command space also contains `STEUERN_ANALOG` / `STEUERN_TACHO_A` /
   `STEUERN_DIGITAL` (drive the gauges, gong, warning lamps) and `SELBSTTEST`. Hitting these
   by accident is noisy but recoverable (ignition cycle). Confidence: high.
4. `KOMBI36.prg` exposes **no coding-write job** (only `CODIERUNG_LESEN`), and
   `KOMBI361.prg` adds only `EEPROM_LESEN`. So the *documented* E36 attack surface does not
   include a coding write — which lowers the "corrupt the coding" risk relative to, say, the
   E39 IKE. Confidence: **medium-high** (absence from the published job list is not proof the
   firmware lacks the command; EDIABAS only exposes what BMW chose to script).
5. garagediag's maintainers independently reached the same conclusion for the E39 IKE:
   *"Do NOT probe blindly — the neighbouring command space includes cluster coding writes."*
   Confidence: high (direct quote from source).

**SPECULATED / unverified risks:**
- "Bricking" the cluster outright (unresponsive, needs replacement) from a bad DS2 *command*:
  I found **no documented case**. DS2 is a request/response protocol with a NACK path
  (ERROR_NACK / 0xFF invalid command), and the cluster's non-volatile content is reached via
  explicit jobs, not by stray bytes landing in EEPROM. Risk of a true brick: judged **low**,
  but this is my inference, not a sourced fact. Confidence: **low**.
- Corrupting coding via a misinterpreted frame: plausible in principle, no documented case
  for E36. Confidence: low.
- Mileage corruption: see KNOWN #1 — this is the realistic bad outcome, not bricking.

**Bottom line on risk:** the scary scenario is not a dead cluster, it is a **zeroed
odometer**. That alone is enough to forbid opcode brute-forcing against 0x80.

---

## 2. E36 cluster + other modules over DS2 — what a status panel could read

### 2.0 The electrical caveat that gates everything `[E36]`

On a Euro/pre-facelift E36, the **DME** answers DS2 on the plain K-line (you already have
this working). The **body modules — KOMBI, ABS/ASC, ZKE** — were historically accessed
through BMW's **ADS** interface ("Aktiver Diagnose Stecker"), which is *not* electrically the
same as a KKL cable: ADS uses **K as TXD and the L line as RXD**, and the BMW ADS adapter is
"one RS232-to-K-line transceiver plus a switch that routes K-line data to the L line based on
the RS232 DTR line". The framing on top is still DS2 ("the software speaks … D2 that all E36
globally will respond to"). Running ADS also required EDIABAS 6.x / INPA ≤ 5.x and a real
serial port.

Sources (forum, could not be fetched in full — Cloudflare/tollbit/403 — content from search
index): https://www.bimmerforums.co.uk/threads/bmw-inpa-e36-obd-obd2-and-ads-interfaces-explained.85191/ ,
https://www.bimmerforums.co.uk/threads/e36-instrument-cluster-kombi-diagnostic.103320/ ,
https://bimmerforums.com/forum/archive/index.php/t-2383900.html
German corroboration (fetched): https://app.fabucar.de/beitraege/864be012-5edd-432a-a5fe-84c109847dd7/tacho-mit-inpa-auslesen-wer-hat-es-geschafft-----bmw-1-
— *"Das Interface muss auf ADS stehen und du benötigst definitiv eine serielle
Schnittstelle"*; the same thread reports reading cluster coding succeeded but **write-back
was refused**. And https://forum.doitauto.de/thread/9199-usb-interface-auslesen-e36-m3-bj-94/
(ADS confirmed working for airbag/IHKA/DME/ABS/VANOS on an E36).

Confidence: **medium-high** that E36 KOMBI/ABS want ADS; **medium** on the exact electrical
description (single forum source, not fetched in full). A related, repeatedly stated
workaround is the "second K-line": on E36/E46 the body modules sit on a second K-line
(OBD-16 pin 8), reachable by bridging pins 7&8 at the cable or by tapping the line behind the
instrument cluster. Confidence: **medium**.

**Practical consequence:** before any of §2.1–2.3 is worth coding, send one **read-only
IDENT** and see if anything answers:
```
80 04 00 84      # IKE/KOMBI ident        (addr, len=4, cmd 0x00, XOR)
56 04 00 52      # ABS/ASC ident
44 04 00 40      # EWS ident
```
These are harmless. If 0x80 never answers on the K-line, the whole software-reset question is
moot for this cable. Confidence that these are the correct, safe ident frames: **high**
(DS2 framing is well established; garagediag uses exactly `request(addr, [0x00])`).

### 2.1 IKE / KOMBI @ 0x80 `[E36]`

Address 0x80 for the cluster is the standard DS2 address and is used by garagediag
(verified on a 1998 E39/M52) and quoted for E36 bench work as "address 0x80, K-line 9600 8E1".
Sources: https://github.com/tooming/garagediag (`E39_MODULES`),
https://www.elektroda.com/qa,bmw-e36-cluster-bench-wiring-k-line.html (search index only —
the page timed out on every fetch attempt).
Confidence: **high** for E39, **medium** for E36 (address space is shared across DS2 cars,
but I have no first-hand E36 capture).

**Ident** — `KOMBI36.prg` `IDENT` takes no arguments and returns:
`ID_GEN_NR` (generation), `ID_HW_NR`, `ID_SW_NR`, `ID_PP_NR` (test-plan no.),
`ID_DATUM_KW` / `ID_DATUM_JAHR` (build week/year), plus `_ANTWORT` (raw telegram).
Note this differs from the E39 `IKE.prg` ident (which returns `ID_BMW_NR`, `ID_COD_INDEX`,
`ID_DIAG_INDEX`, `ID_BUS_INDEX`, `ID_LIEF_NR`, …) — **do not reuse an E39 ident parser.**
Source: `docs/sgbd/KOMBI36.md` vs `docs/sgbd/IKE.md`. Confidence: high.

**Readable live values** — `STATUS_LESEN` (args `K_ZAHL`, `KVA`, `MOTORFAKTOR`) returns, per
the SGBD:
- `STAT_U_BATT_WERT` battery volts (2–24.8 V)
- `STAT_TEMPERATUR_WERT` [°C] (coolant/outside per coding)
- `STAT_TANKINHALT_WERT` **fuel level [litres]**
- `STAT_OELTEMPERATUR_WERT` [°C] *or* `STAT_KVA_SIGNAL_WERT` [ms] depending on
  `STAT_KVA_ODER_OELTEMPERATUR_VERBAUT`
- `STAT_DREHZAHL_SIGNAL_WERT` 0–10000 rpm
- `STAT_GESCHWINDIGKEIT_SIGNAL_WERT` **road speed [km/h]**
- `STAT_HELLIGKEIT_FOTOTRANSISTOR_WERT` [%] (light sensor)
- `STAT_KLEMME_58g_LOW/HIGH` [ms] (dimmer PWM)
- digital inputs: `STAT_KLEMME_R_EIN`, `STAT_KLEMME_15_EIN`, **`STAT_SIA_RESET_EIN`**,
  `STAT_BREMSBELAGVERSCHLEISSANZEIGE_EIN` (pad wear), `STAT_GURTKONTAKT_EIN`,
  `STAT_ZUENDSCHLOSSKONTAKT_EIN`, `STAT_FAHRERTUERKONTAKT_EIN`
- `TELEGRAMM` raw response
Source: `docs/sgbd/KOMBI36.md`. Confidence: **high** that these fields exist; the byte
offsets inside the telegram are **not** published — you would have to map them empirically
(garagediag does exactly this for the E39 by polling `0B 0A` and diffing bytes).

Note `STAT_SIA_RESET_EIN` is a **status bit for the pin-7 SIA reset input**, and the fault
table has `0x0F = "SIA-Eingang defekt"`. That is direct evidence that on the E36 the pin-7
line is a hardware input **into the cluster** — the cluster, not some other module, owns the
SIA reset. Confidence: **high**. (Useful: you can read this bit to verify a paperclip reset
is actually making contact.)

**VIN:** `FG_NR_LESEN` → `FG_NR` (Fahrgestellnummer). Also present inside
`CODIERUNG_LESEN`'s result set. Confidence: high that the job exists; whether an early E36
cluster has a VIN stored depends on whether the EEPROM was coded — `CODIERUNG_LESEN` returns
`EEPROM_CODIERT` (j/n) for exactly that reason.

**Odometer:** `KOMBI36.prg` has **no** `AIF_GWSZ_LESEN` job — that one exists on the E39
`IKE.prg` and on `KOMBI36C.prg`, not on the plain E36 cluster. Odometer on a plain E36
cluster would have to come from `SPEICHER_LESEN` / `EEPROM_LESEN` (raw address reads,
1–16 bytes at a time) with an address map you do not have. Confidence: **high** that the job
is absent; **low** that a practical odometer read is achievable without reverse engineering.
`[E39/E38]` contrast: `IKE.prg` *does* have `AIF_GWSZ_LESEN`, `AIF_FG_NR_LESEN`,
`AIF_SIA_DATEN_LESEN` (SIA data block!), `AIF_ZENTRALCODE_LESEN`, `AIF_DATUM_FZ_LESEN`,
`STATUS_TANKINHALT_LESEN`. **None of those are in the E36 cluster SGBD** — this is the single
biggest E36-vs-E39 trap in this whole area.

**Outside temperature:** on an E36 the outside-temp sensor feeds the OBC/IHKA, not clearly the
cluster; the cluster's `STAT_TEMPERATUR_WERT` is a generic temperature status with no stated
source. Confidence: **low** — treat "outside temp from 0x80" as unverified.

**Faults:** `FS_LESEN` / `FS_LOESCHEN` exist. The **fault-location table is public** —
`KOMBI36.prg` table `FORTTEXTE` (22 entries), which you can ship verbatim:

| code | meaning |
|---|---|
| 0x00 | internal fault (RAM) |
| 0x05 | EEPROM read error |
| 0x07 | k-factor (K-Zahl) faulty |
| 0x08 | A/D converter, conversion time exceeded |
| 0x09 | supply fault, KL.15 high / KL.R low |
| 0x0A | KL.15 overvoltage |
| 0x0D | overcurrent, gauges |
| 0x0E | PCVA thermally overloaded |
| 0x0F | SIA input defective |
| 0x10 | fuel level sender defective |
| 0x11 | coolant temperature sender defective |
| 0x13 | oil temperature sender defective |
| 0x15 | 5 V supply disturbed |
| 0x16 | KOMBI button defective |
| 0x18 | speed signal disturbed |
| 0x19 | rpm signal disturbed |
| 0x1A | injection signal disturbed |
| 0x1B | brake pad wear |
| 0x1C | fuel reserve contact |
| 0x1E | driver door contact |
| 0x1F | ignition key contact |
| 0xFF | unknown fault location |

and `FARTTEXTE` (fault type, 2nd byte): 0x00 short to Ubatt, 0x01 short to ground,
0x02 open circuit, 0x03 invalid operating range, 0x04 intermittent, 0x05 static,
0xFF unknown.
Source: `docs/sgbd/KOMBI36.md`. Confidence: **high**.

### 2.2 ABS / ASC @ 0x56 `[E36]`

The E36-correct SGBDs are **`ABSMK20.prg`** (ECU string *"Antiblockiersystem MK20 E36"*) and
**`ASCMK20.prg`** (ECU string *"ABS/ASC, ITT_Industries, MK20E_I, E36,E46"*). `ABS5.prg` /
`ASC5.prg` are **E31/E32/E34/E38 only** — do not use them as an E36 reference.
Source: https://github.com/emdzej/ediabasx-docs-sgbd → `docs/sgbd/ABSMK20.md`, `ASCMK20.md`,
`ABS5.md`, `ASC5.md`. Confidence: **high**.

Supported: `IDENT`, `FS_LESEN` (+ `FS_LESEN_KB90` variant), `FS_LOESCHEN`, `FS_INIT`
(NVRAM erase), `STATUS_IO_LESEN`, plus a large actuator set (`STEUERN_DIGITAL` over
EVVL/AVVL/EVVR/AVVR/EVHA/AVHA/PUMPE, pressure build/release, pump output tests).

`STATUS_IO_LESEN` on `ABSMK20` returns: four **wheel speeds** (`STAT_RAD_GESCHW_VL/VR/HL/HR`,
km/h) and `STAT_BREMSLICHT_SCHALTER_EIN` (brake light switch), plus `_AUFTRAG1`/`_ANTWORT1`
raw telegrams. `ASCMK20` adds `STATUS_SPANNUNGSWERTE_LESEN` and `STATUS_DME_DDE_1`.
Confidence: high.

**Hard constraint:** `ABSMK20` header says *"Keine Diagnose bei V > 2.5 km/h"*; `ASCMK20` says
*"Keine Diagnose bei V > 6 km/h"*. Your status panel must not try to talk to 0x56 while
driving. Confidence: **high**.

Address 0x56: from garagediag's verified DS2 map (E39). Confidence: high for E39, **medium**
for E36. Also note one forum data point that INPA on a 1999 E36 323i failed to read ABS/ASC:
https://www.bimmerforums.co.uk/threads/1999-e36-323i-inpa-not-reading-abs-asc-system.84904/
(search index only) — consistent with the ADS story in §2.0.

### 2.3 EWS @ 0x44 `[E36]`

A 1996 E36 has **EWS II**, whose SGBD is **`EWS.prg`** — ECU string *"Elektronische
Wegfahrsperre 2 - alle Typen"*. `EWS3.prg` is the EWS III development SGBD (later cars).
Source: https://github.com/emdzej/ediabasx-docs-sgbd → `docs/sgbd/EWS.md`, `EWS3.md`.
Confidence: **high** on what the files are; **medium** that your specific 1996 Euro car is
EWS II (needs checking against the car — EWS II ran roughly 1995–1997).

`EWS.prg` supports: `IDENT`, `FS_LESEN`, `FS_LOESCHEN`, `DIAGNOSE_ENDE`,
`DIAGNOSE_FORTSETZEN`, `COD_LESEN`, `HERSTELLDATEN_LESEN/SCHREIBEN`, `STATUS_LESEN`,
`STEUERN_DIGITAL`, `ISN_LESEN/SCHREIBEN`, `WECHSELCODE_SYNC_DME`, `SCHL_SPERREN_FREIGEBEN`,
`PASSWORT_LESEN/SCHREIBEN`, `SCHL_DATEN_LESEN/…`. So ident + DTC read/clear + status are all
available. Confidence: high.

**Danger zone:** `ISN_SCHREIBEN`, `PASSWORT_SCHREIBEN`, `SCHL_DATEN_SCHREIBEN`,
`SCHL_SPERREN_FREIGEBEN` can immobilise the car / lock out keys. Any e36cli EWS support
should be **read-only, hard-coded** (0x00 ident, 0x04 faults, and nothing else).
Confidence: high (these are write jobs to immobiliser secrets by name).

### 2.4 Open-source prior art summary

| project | what it gives you | relevance |
|---|---|---|
| https://github.com/tooming/garagediag | Working Python DS2 (9600 8E1, XOR), module map 0x00–0xD0 incl. 0x80/0x56/0x44, ident/faults/clear/live, fault-text JSONs, honest `sia_reset` stub | **highest** — closest architecture to e36cli, but verified on **E39**, not E36 |
| https://github.com/emdzej/ediabasx-docs-sgbd | Machine-extracted docs for every SGBD incl. **KOMBI36 / KOMBI361 / KOMBI36C / ABSMK20 / ASCMK20 / EWS** — jobs, args, results, lookup tables | **highest** for E36-correct semantics; job-level only, **no raw telegrams** |
| https://github.com/handmade0octopus/ds2 | Arduino/ESP32 DS2 framing lib | framing reference only |
| https://github.com/opetany93/ds2-protocol | Rust DS2 framing | framing reference only |
| https://github.com/oleavr/bmw-coding | `ds2.py`, coding reads | coding-read reference |
| https://github.com/tomicooler/bmwe46oil | E46/MS43 **oil temperature** over DS2 (Qt/Android) + a good DS2 write-up | `[E46]`, and it is *not* a service reset despite the name |
| https://github.com/radelbro/BimmerDis | disassembles `.prg` into readable data | **the route to the real opcode** if you can obtain `KOMBI36.prg` |

Confidence: high (all cloned/read directly except BimmerDis, which is from search results —
medium).

---

## 3. Go / No-Go recommendation

### SIA reset in software on a 1996 E36: **NO-GO as a shipped feature.**

Reasoning, in order of weight:

1. **The request bytes do not exist in public.** The job exists (`KOMBI36.prg::SIA_RESET`) and
   the selector values are known (0x01/0x02/0x03/0x04), but nobody has published the DS2
   opcode, and the one open-source project that tried (garagediag, on an E39) got
   `0xFF invalid command` for its guess and wrote "do NOT probe blindly" into its own source.
2. **Brute-forcing the opcode is the one thing we must not do.** `KOMBI36.prg` exposes
   `GWSZ_RESET` — **odometer reset, zero arguments** — in the same command space. The failure
   mode is not a wasted afternoon, it is a zeroed odometer on a 30-year-old car, which is
   irreversible without EEPROM work and is a legal problem on resale.
3. **The transport probably isn't there anyway.** On a Euro E36 the cluster historically needs
   an **ADS** interface (K as TXD, L as RXD, DTR-switched), not the KKL cable that works fine
   for the DME at 0x12. Until an ident at 0x80 actually answers, this is all theoretical.
4. **The alternative is genuinely trivial and genuinely zero-risk.** Pin 7 → pin 19,
   ignition II, ~3–4 s for oil / ~10–12 s for inspection, count the LED flashes. No code, no
   risk, works on every E36.

### What I'd actually build

- **Ship the pin-7 procedure as a documented, interactive CLI helper, not as a bus write.**
  A `e36cli service reset` that prints the connector location, the pin diagram, the two
  timings, and runs an on-screen countdown timer (3.5 s / 11 s) is more useful than the real
  thing and cannot hurt the car. Optionally poll `STAT_SIA_RESET_EIN` from the cluster (if
  0x80 answers) to show "jumper detected / not detected" live — that turns a guessing game
  into a verified procedure. **GO.**
- **Read-only cluster/ABS/EWS status panel: conditional GO.** Step 1 is a cheap experiment:
  send `80 04 00 84`, `56 04 00 52`, `44 04 00 40` and see what answers. If 0x80 answers,
  implement `IDENT` (E36 field layout, **not** the E39 one), `FS_LESEN` with the `FORTTEXTE`
  / `FARTTEXTE` tables above, and map `STATUS_LESEN` empirically by diffing bytes with the
  engine off/on, tank moving, door open/closed. If it does not answer, document "cluster
  needs ADS" and move on.
- **Never implement** at 0x80: `GWSZ_RESET`, `STEUERN_*`, `SELBSTTEST`, any 0x07 coding write.
  At 0x44: anything containing `SCHREIBEN`, `ISN`, `PASSWORT`, `SCHL_`. At 0x56: anything
  `STEUERN_*` / `DRUCK*` / `FS_INIT`, and gate even reads on speed ≤ 2.5 km/h.
- **The one path to a real software reset**, if you ever want it: obtain `KOMBI36.prg` from an
  SP-Daten set and disassemble it (BimmerDis, or the `sgbd_parser.py` already in garagediag)
  to recover the literal telegram that `SIA_RESET` builds. That turns a guess into a fact.
  Until then, the honest answer is the paperclip.

---

## Appendix: sources used

- https://pinoutguide.com/CarElectronics/car_diag_pinout.shtml — 20-pin round connector pinout
- https://www.bmwclubgoldcoast.com/home/tech-tips/reset-service-indicator-round-plug — procedure, ~4 s / 10 s
- https://bimmertips.com/reset-e36-oil-service-inspection-light-how-to/ — procedure, ~4 s, "all E36 OBDI and OBDII"
- https://www.department69.com/articles/how-to-reset-bmw-e36-oil-service-light-with-a-paperclip — procedure, 3–5 s
- https://technicae.wordpress.com/2012/05/09/bmw-e36-olservice-und-inspektionsanzeige-zurucksetzen/ — 3 s / 12 s
- https://e36-wartung.e36-page.net/wartung-e36-serviceanzeige.html — 3 s / 12 s
- https://steemit.com/cars/@peterschroeter/diy-reset-the-service-interval-display-notification-on-any-bmw-built-between-1982-1999-e30-e46-e39-e36-etc — 7 flashes / 23 flashes, 1982–1999 scope
- https://www.unofficialbmw.com/e36/electrical/e36_reset_service_lights.html — classic write-up (site unreachable at fetch time; search index only)
- https://github.com/emdzej/ediabasx-docs-sgbd — KOMBI36 / KOMBI361 / KOMBI36C / IKE / ABSMK20 / ASCMK20 / ABS5 / ASC5 / EWS / EWS3 SGBD job+table docs (browsable: https://emdzej.github.io/ediabasx-docs-sgbd/)
- https://github.com/tooming/garagediag — open-source DS2 implementation, module map, `sia_reset` stub and its warnings
- https://github.com/handmade0octopus/ds2 , https://github.com/opetany93/ds2-protocol , https://github.com/oleavr/bmw-coding , https://github.com/tomicooler/bmwe46oil — other DS2 code checked (no service reset in any)
- https://app.fabucar.de/beitraege/864be012-5edd-432a-a5fe-84c109847dd7/tacho-mit-inpa-auslesen-wer-hat-es-geschafft-----bmw-1- — E36 cluster needs ADS + serial; coding write-back refused
- https://forum.doitauto.de/thread/9199-usb-interface-auslesen-e36-m3-bj-94/ — ADS interface on E36 M3
- https://www.bimmerforums.co.uk/threads/bmw-inpa-e36-obd-obd2-and-ads-interfaces-explained.85191/ , https://www.bimmerforums.co.uk/threads/e36-instrument-cluster-kombi-diagnostic.103320/ , https://www.bimmerforums.co.uk/threads/1999-e36-323i-inpa-not-reading-abs-asc-system.84904/ , https://bimmerforums.com/forum/archive/index.php/t-2383900.html — ADS vs OBD on E36, second K-line (403/402-blocked; content via search index only, confidence reduced accordingly)
- https://www.bimmerfest.com/threads/how-do-i-do-a-oil-reset-with-inpa.1372603/ — "you cannot reset E36 service interval with INPA/DIS" (search index only)
- https://www.elektroda.com/qa,bmw-e36-cluster-bench-wiring-k-line.html — E36 cluster bench wiring, K-line on X16-12, 0x80 @ 9600 8E1 (page timed out on every fetch; search index only)
- http://markgardnergibson.com/BMW/protocol.html — DS2 frame format (unreachable at fetch time; corroborated by garagediag)
