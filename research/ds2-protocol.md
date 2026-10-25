# BMW DS2 protocol reference (K-line, E36 / MS41.x DME)

Compiled 2026-10-25 for a Python CLI talking DS2 over an FTDI KKL cable on Linux.

Every concrete fact carries an inline source URL and a confidence tag:

* **[high]** — ≥3 independent sources agree, or confirmed by working source code plus a captured
  bus trace.
* **[medium]** — 2 independent sources, or one source that is working code.
* **[low]** — single source, inferred, or contradicted elsewhere (see §7).

---

## 1. Physical / serial layer

### 1.1 Line parameters

| Parameter | Value | Confidence | Source |
|---|---|---|---|
| Baud rate | **9600** | [high] | <https://github.com/RomRaider/RomRaider/blob/master/src/main/java/com/romraider/io/protocol/ds2/iso9141/DS2Protocol.java> (`getBaudRate() { return 9600; }`), <https://github.com/muki01/OBD2_KLine_Library/blob/main/src/KLine_Protocol.cpp>, <https://github.com/0xDevDav/EWSync>, <https://allpinouts.org/pinouts/connectors/car/obd-ii-bmw-vehicle-diagnostic/> |
| Data bits | **8** | [high] | RomRaider `getDataBits() { return 8; }`, same URL as above |
| Parity | **Even** | [high] | RomRaider `getParity() { return 2; }` (javax.comm `PARITY_EVEN==2`); EdiabasLib `parity = SerialParity.Even;` for concept `0x0006 // DS2` <https://github.com/uholeschak/ediabaslib/blob/master/EdiabasLib/EdiabasLib/EdInterfaceObd.cs>; `serial.PARITY_EVEN` in <https://github.com/oleavr/bmw-coding/blob/master/ds2.py>; `SERIAL_8E1` in muki01 `DS2_CONFIG`; `Serial.begin(9600, SERIAL_8E1)` in the MS41 Arduino sketch <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660> |
| Stop bits | **1** | [high] | RomRaider `getStopBits() { return 1; }` |
| **Framing summary** | **9600 8E1** | [high] | as above. See §7 for the one dissenting source claiming 8N1. |

### 1.2 Wake-up / init

* **There is no 5-baud slow init, no fast init, no keyword exchange, and no session handshake for
  DS2.** You open the port at 9600 8E1 and immediately send a request frame. [high]
  * muki01's library classifies DS2 as `Init_Ping` and the "handshake" is literally sending the
    one-byte ident payload `0x00` and seeing whether anything answers:
    `const uint8_t pingData[] = {0x00}; // DS2 simple ping`
    <https://github.com/muki01/OBD2_KLine_Library/blob/main/src/KLine_Protocol.cpp>
  * EdiabasLib sets `EcuConnected = true;` directly in the DS2 concept case, with no
    `ParWakeAddress` and no `ParHasKeyBytes` (contrast concept `0x0002` ISO9141/KWP1281, which sets
    `ParWakeAddress` and `ParHasKeyBytes = true`).
    <https://github.com/uholeschak/ediabaslib/blob/master/EdiabasLib/EdiabasLib/EdInterfaceObd.cs>
  * garagediag's module docstring: "No session/init handshake is needed."
    <https://github.com/tooming/garagediag/blob/main/ds2_diag.py>
* The conventional probe is the DME identification request `12 04 00 16`; if a valid frame comes
  back the bus is alive. [high] (muki01, <https://github.com/handmade0octopus/ds2>, the Arduino
  sketch above, EWSync.)
* Ignition must be ON (KL15, position 2) for the DME to answer. [medium]
  <https://github.com/tooming/garagediag> ("Ignition must be ON (position 2)").

### 1.3 K-line echo

* The K-line is a single-wire open-collector bus, so **everything you transmit is echoed back into
  your own receiver**. You must read and discard exactly `len(request)` bytes before the response.
  [high]
  * handmade0octopus: "Echo - if you send any command on DS2 it responds with whatever was send due
    to way K-line is like constructed." <https://github.com/handmade0octopus/ds2>
  * oleavr `ds2.py`: `self._write(...); echo = self._read(); reply = self._read()`
  * EdiabasLib removes the echo and byte-compares it against the sent frame, failing with
    `EDIABAS_IFH_0003` ("Echo incorrect") on mismatch — useful as a collision/own-transmit check.
    `EdInterfaceObd.cs::TransDs2`
  * garagediag strips the echo by matching the exact sent bytes and additionally strips leading
    `0x00` bytes as bus noise. `ds2_diag.py::DS2.request`
* Caveat: some interfaces (EdiabasLib's "adapter echo" concept, J2534 boxes) suppress the echo in
  hardware. A plain FTDI KKL cable does **not** — plan for echo, but make it tolerant (match-and-
  strip rather than blind `read(n)`). [medium] (EdiabasLib `HasAdapterEcho` branch.)

### 1.4 Timing

| Item | Value | Confidence | Source |
|---|---|---|---|
| Inter-byte time within a sent frame | 0 by default (`ParInterbyteTime` comes from the ECU's comm-parameter set and is usually 0) | [medium] | EdiabasLib `ParInterbyteTime = (int)CommParameterProtected[8]` for DS2, and `SendData(..., ParInterbyteTime)` |
| Some ECUs need a per-byte gap | e.g. DDE4; library exposes `setSlowSend(delay)` | [low] | <https://github.com/handmade0octopus/ds2> (`// Some ECUs like DDE4 need delay between bytes sent`) |
| P1 (inter-byte, receive) | 20 ms | [low] | muki01 `DS2_CONFIG` P1 |
| P2 (request→response) | 1000 ms budget | [low] | muki01 `DS2_CONFIG` P2 |
| P3 (response→next request) | 57 ms | [low] | muki01 `DS2_CONFIG` P3 |
| P4 | 5 ms | [low] | muki01 `DS2_CONFIG` P4 |
| RomRaider "send timeout" (gap between queries) | **55 ms** | [medium] | RomRaider `DS2Protocol.getDefaultConnectionProperties().getSendTimeout()` |
| RomRaider connect timeout | 2000 ms | [medium] | same |
| Practical delay between requests used by a working MS41 logger | **112 ms** (`const uint8_t ISORequestDelay = 112; // Time between requests`) | [medium] | Arduino MS41 sketch, <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660> |
| Delay to work around flaky multi-module polling | 30 ms between queries to different modules | [low] | oleavr `ds2.py` (`time.sleep(0.03)`) |
| Per-request response timeout actually used in the field | ident/status 0.4 s, fault read 0.8 s, **clear faults 1.5 s** | [medium] | garagediag `ds2_diag.py` |
| Observed MS41 throughput | 8–10 query/s for the 29-byte `12 05 0B 03` group; ECU-limited, not line-limited | [medium] | dschultz, <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=45> |
| Observed MS41 request→response latency | ~78–94 ms in EDIABAS traces (timestamps 15859→15937, 23391→23485) | [medium] | trace excerpts in <https://romraider.com/forum/viewtopic.php?f=42&start=0&t=11086> and `...&start=15` |

EdiabasLib also enforces a *regeneration* gap (`ParRegenTime`) by busy-waiting since the last
response before sending again — a good model: `while ((now - LastResponseTick) < ParRegenTime) sleep(1)`.
[medium] `EdInterfaceObd.cs::TransDs2`.

### 1.5 DTR / RTS

* **DS2 asserts DTR** in EdiabasLib: in the `case 0x0006: // DS2` branch,
  `if (concept == 6) { /* DS2 uses DTR */ ParSendSetDtr = !HasAdapterEcho; }`, whereas DS1
  (`0x0005`) leaves `ParSendSetDtr = false`. [medium]
  <https://github.com/uholeschak/ediabaslib/blob/master/EdiabasLib/EdiabasLib/EdInterfaceObd.cs>
* On many KKL cables DTR/RTS gate the K-line driver or power the opto-isolator. Make DTR/RTS state
  configurable in the CLI; if the car does not answer, try toggling them. [low] (inference from the
  above plus common KKL schematics.)

### 1.6 FTDI latency on Linux

* The FT232 buffers received bytes and flushes on a timer whose **default is 16 ms**; on Linux it is
  exposed per device as `/sys/bus/usb-serial/devices/ttyUSB0/latency_timer` and can be set to `1`.
  The value **resets on re-enumeration**, so script it or use a udev rule. [medium]
  <https://www.techeia.com/blog/ftdi-sio-linux-usb-serial-driver-setup>,
  <https://industrialmonitordirect.com/blogs/knowledgebase/ftdi-latency-timer-fixing-625-hz-serial-sensor-rate>
* Consequence for DS2: at 9600 baud a byte is ~1.04 ms, a 29-byte frame ~30 ms. A 16 ms latency
  timer adds up to 16 ms of jitter per read chunk, which is tolerable, but it will cap your poll
  rate and make byte-at-a-time state machines slow. Setting `latency_timer=1` is the standard fix.
  [medium] (derived from the above.)
* Counter-data point: EdiabasLib's Android FTDI backend deliberately uses a **large** latency
  (`int latencyTime = 50 // large default value required to prevent data loss`). [medium]
  <https://github.com/uholeschak/ediabaslib/blob/master/EdiabasLib/EdiabasLib/EdFtdiInterfaceAndroid.cs>
  Interpretation: large latency = fewer, bigger USB transfers = less chance of overrun on a slow
  host. On desktop Linux with a read thread, prefer `latency_timer=1`. Make it configurable.
* garagediag reports it had to bypass pyserial entirely and use raw termios on macOS with K+DCAN
  cables; on Linux pyserial over `ftdi_sio` is normally fine, but note the precedent. [low]
  <https://github.com/tooming/garagediag/blob/main/ds2_diag.py>
* Practical: set `timeout` small (e.g. 0.02–0.05 s) and loop-accumulate into a buffer rather than
  doing one blocking `read(n)` — that is what both garagediag and the Rust crate do
  (`receive_exact` loops until the frame is complete). [medium]
  <https://github.com/opetany93/ds2-protocol/blob/master/src/lib.rs>

---

## 2. DS2 frame format

### 2.1 Request frame

```
+---------+--------+-------------------+----------+
| address |  len   |  payload (n bytes)|  XOR cks |
+---------+--------+-------------------+----------+
   1 byte   1 byte        n bytes          1 byte
```

* `address` = target module diagnostic address (e.g. `0x12` for the DME). [high]
* **`len` counts the ENTIRE frame**: address + len + payload + checksum. So
  `len = n + 3`. [high]
  * oleavr: `size = 2 + len(payload) + 1`
  * muki01: `lengthIncludesFrame = true // the length counts the whole frame`, and
    `// DS2 length includes EVERYTHING: Header(1) + Len(1) + Payload + Checksum(1)`
  * opetany93 Rust crate README: "`length` covers the whole frame, including address and checksum
    (3 to 255 bytes)."
  * garagediag: `msg = bytes([addr, len(payload) + 3]) + bytes(payload)`
  * RomRaider `buildRequest`: `int length = 3; length += command.length; length += readLen.length; ...`
* `checksum` = **XOR of every preceding byte of the frame**, i.e. of address, len and all payload
  bytes. Initial value 0. [high] — all of the above sources, plus the original author of the MS41
  logger: "basically just xor the bytes" with Qt code
  <https://romraider.com/forum/viewtopic.php?f=42&start=0&t=11086> (page 2), and EdiabasLib
  `CalcChecksumXor`.

Canonical worked example (identification request to the DME):

```
12 04 00 16
^  ^  ^  ^
|  |  |  +-- 0x12 ^ 0x04 ^ 0x00 = 0x16
|  |  +----- payload: command 0x00
|  +-------- total frame length = 4
+----------- DME address
```
[high] — <https://github.com/handmade0octopus/ds2>, <https://github.com/opetany93/ds2-protocol>,
the MS41 Arduino sketch, muki01.

Second example (17-parameter MS41 status group): `12 05 0B 03 1F`, where
`0x12^0x05^0x0B^0x03 = 0x1F`. [high] same sources.

Maximum payload: the length byte is 8-bit, so a frame is at most 255 bytes → payload ≤ 252 bytes
(`CommandTooLong` if exceeded). [medium]
<https://github.com/opetany93/ds2-protocol/blob/master/src/lib.rs>

### 2.2 Response frame

```
+---------+--------+--------+-------------------+----------+
| address |  len   | status |   data (n bytes)  |  XOR cks |
+---------+--------+--------+-------------------+----------+
```

* `address` in the response is the **sender's own address**, i.e. it equals the address you
  requested. Reject frames whose address ≠ requested address. [high] (oleavr `if sender != address:
  raise ProtocolError`; Rust crate `UnexpectedAddress`; RomRaider `assertEquals(module.getAddress()[0],
  response[0], "Invalid ... id")`; garagediag `want_addr` filtering.)
* `len` again counts the whole frame. EdiabasLib expresses this as `CommAnswerLen[0] = -1`, meaning
  "telegram length is at buffer offset 1, with offset 0 added", i.e. `telLength = dataBuffer[1]`.
  [high] `EdInterfaceObd.cs::TelLengthDs2`
* `status` (payload byte 0) is the ACK/NAK byte. [high]
* **Non-data overhead = 4 bytes** (addr, len, status, cks); payload data length = `len - 4`.
  RomRaider: `RESPONSE_NON_DATA_BYTES = 4` and the comment `// 12 <length> a0 <bytes> <checksum>`.
  [high]
  <https://github.com/RomRaider/RomRaider/blob/master/src/main/java/com/romraider/io/protocol/ds2/iso9141/DS2ResponseProcessor.java>
* Checksum: same XOR rule over all bytes before the checksum. [high]

Worked examples from real EDIABAS traces (MS41.1, ECU `MS411DS1`):

```
request : 12 05 0B 03        -> response: 12 1D A0 00 00 00 24 00 00 D3 E0 4F 00 00 24 5C 98
                                          7C 00 7E 80 00 80 00 06 06 00 00 15
request : 12 09 0B 02 0E 00 00 01 -> response: 12 06 A0 00 FA 4E      (= 4.825 V)
request : 12 05 0B 04        -> response: 12 07 A0 21 00 01 95
```
[high] <https://romraider.com/forum/viewtopic.php?f=42&start=0&t=11086> and
<https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=15>

Verify the last one: `0x12^0x07^0xA0^0x21^0x00^0x01 = 0x95`. ✔

### 2.3 Status / ACK bytes

| Byte | Meaning | Confidence | Source |
|---|---|---|---|
| `0xA0` | **OK / positive response**; data follows | [high] | oleavr `ds2.py`, RomRaider `VALID_RESPONSE = (byte) 0xA0`, handmade0octopus, garagediag `STATUS_BYTE`, pBmwScanner, every captured trace |
| `0xA1` | **Computer busy** (ECU busy, retry) | [high] | oleavr (`ComputerBusy`), garagediag (`0xA1: "busy"`), pBmwScanner, d_munter's MS41 command table lists `A1` as a possible reply to commands `0x0A` |
| `0xA2` | **Invalid parameter** | [high] | oleavr (`"invalid parameter"`), garagediag (`0xA2: "invalid parameter"`), pBmwScanner; d_munter lists `A2` for `0x07`, `0x31`, `0x41`, `0x90` |
| `0xB0` | **Negative / command rejected** (MS41 returns this e.g. when the read command's mode byte is not `0x00`) | [medium] | <https://github.com/handmade0octopus/ds2> ("A0 meaning positive response, B0 being negative"); d_munter's MS41 table repeatedly lists `B0` as an alternative reply for `0x06`, `0x07`, `0x0B`, `0x40`, `0x41`, `0x42`, `0x2B`, `0x90`; "00 (00 for read, else ack=B0!!!)" <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=30> |
| `0xFF` | **Invalid / unsupported command** | [high] | oleavr, garagediag (`0xFF: "invalid command"`), pBmwScanner; garagediag observed a real `0xFF` when probing an undocumented IKE command |
| anything else | protocol error — treat as unknown status | [high] | oleavr, pBmwScanner |

Note `0xA0`/`0xA1`/`0xA2`/`0xFF` are the set agreed by four independent implementations; `0xB0` is
attested only by the MS41 reverse-engineering work and the Arduino library (see §7).

### 2.4 Recommended receive algorithm

Taken from garagediag (`_read_frame`) and the Rust crate, both of which handle real-world noise:

1. Drop leading `0x00` bytes (bus noise / break conditions).
2. Need ≥2 bytes; take `ln = buf[1]`. Sanity-check `3 <= ln <= 255` (garagediag uses `<= 120`);
   if implausible, drop one byte and resync.
3. Wait for `ln` bytes total, verify `xor(frame[:-1]) == frame[-1]`; on mismatch drop one byte and
   resync.
4. If `frame[0] != requested_address`, discard and keep waiting — garagediag notes that **some ECUs
   (notably the DME) emit unsolicited/cyclic frames** that otherwise get misattributed. [medium]
5. Retry the whole request once after ~50 ms on timeout (garagediag default `retries=1`).

---

## 3. Module addresses (E36 / E39-era DS2 bus)

The DS2 diagnostic address space is the same 8-bit space as the BMW I/K/D-bus device index, so the
two tables corroborate each other.

| Addr | Module | Confidence | Source |
|---|---|---|---|
| `0x00` | GM / ZKE — general body module | [high] | <https://github.com/tooming/garagediag/blob/main/docs/MODULES.md>, <https://github.com/piersholt/wilhelm-docs/blob/master/address.md> ("General Module (GM)") |
| `0x08` | SZM switch centre / sunroof (SHD) | [medium] | garagediag (`SZM`), wilhelm-docs (`Tilt/Slide Sunroof (SHD)`) |
| `0x11` | Central body electronics ZKE1/ZKE2 (D-bus) | [low] | wilhelm-docs |
| **`0x12`** | **DME / Motronic (engine)** | [high] | garagediag, wilhelm-docs, oleavr (`MOTRONIC = 0x12`), EWSync, muki01 (`initAddress 0x12 (DME)`), handmade0octopus, every MS41 trace |
| `0x16` | Thermal level oil sensor [E36] | [low] | wilhelm-docs |
| `0x18` | CDC — CD changer | [medium] | garagediag, wilhelm-docs |
| `0x21` | Central locking module [E34, E36] | [low] | wilhelm-docs |
| `0x32` | EGS — automatic transmission | [high] | garagediag, wilhelm-docs (`Transmission`), oleavr (`AUTOMATIC_TRANSMISSION = 0x32`) |
| `0x44` | **EWS — immobiliser / drive-away protection** | [high] | garagediag, wilhelm-docs, EWSync (`EWS_ADDRESS = 0x44`) |
| `0x45` | DWA — anti-theft alarm | [low] | wilhelm-docs |
| `0x50` | MFL — multifunction steering wheel | [medium] | garagediag, wilhelm-docs |
| **`0x56`** | **ABS / ASC / DSC** | [medium] | <https://github.com/tooming/garagediag/blob/main/docs/MODULES.md> (verified on car, has fault texts). Not present in wilhelm-docs' I/K-bus table — ABS is a D-bus/diagnostic-only node. |
| `0x5B` | IHKA — automatic climate control | [high] | garagediag, wilhelm-docs |
| `0x60` | PDC — park distance control | [medium] | garagediag, wilhelm-docs |
| `0x68` | Radio | [medium] | garagediag, wilhelm-docs |
| `0x6A` | DSP — digital sound processor | [medium] | garagediag, wilhelm-docs |
| `0x70` | RDC — tyre pressure | [low] | wilhelm-docs |
| **`0x80`** | **IKE / KOMBI — instrument cluster** | [high] | garagediag, wilhelm-docs, oleavr (`IKE = 0x80`) |
| `0xA4` | **MRS — airbag / multiple restraint system** | [medium] | garagediag (`MRS (airbag)`), wilhelm-docs (`Multiple Restraint System (MRS)`) |
| `0xAC` | EHC — electronic height control | [low] | wilhelm-docs |
| `0xC0` | MID — multi-information display | [medium] | garagediag, wilhelm-docs |
| `0xC8` | TEL — telephone | [medium] | garagediag, wilhelm-docs |
| **`0xD0`** | **LCM / LSZ — light check module** | [high] | garagediag, wilhelm-docs, oleavr (`LCM = 0xD0`) |

Notes:

* garagediag's table is labelled "E39 (DS2) modules" and verified on an E39; the E36 fitment is a
  subset (no DSP/PDC/MID on most E36). The addresses themselves are chassis-independent — the
  wilhelm-docs table explicitly says addresses were allocated once and never reused. [medium]
* A brute-force sweep of `0x00–0xFF` with the ident command `AA 04 00 cks` is the reliable way to
  enumerate what a particular car actually has; garagediag ships exactly that (`sweep` mode). [high]
* Warning: `0x3F` is the diagnostic gateway address and `0xBF`/`0xFF` are broadcast addresses on the
  I/K bus — do not sweep-write to them. [medium] wilhelm-docs.
* On later cars the addressing changes completely (E87/E90 KWP2000: MRS is `0x01`, DSC is `0x29`).
  Don't reuse this table for post-2001 cars. [high] garagediag `docs/MODULES.md`.

---

## 4. MS41 DS2 command set

The authoritative open source for this is d_munter's disassembly of the MS41 firmware, posted on
RomRaider: <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=45> — reproduced below
with the original annotations. Treat the whole table as **[medium]** unless a specific line is
cross-confirmed by a trace or by RomRaider/garagediag source (noted per line).

### 4.1 Command byte table (address `0x12`)

```
00  (ROOT) read status / identification, ACK: A0
04  read the error memory
05  clear trouble codes
06  (ROOT) read data from address [00 SG HI LO NN]  NN < 0xF9 bytes, ACK: A0, B0
07  (ROOT) write data [06|02|0F SG HI LO NN ...]    NN < 0xF9 bytes,
        ACK: [12 0A A0 06|02|0F HH+ MM+ LL+ NN ...], A2, B0
0A  (ROOT) coding / calibration CRC status,         ACK: [12 05 A0 NN], A1, A2
0B  read coded data / IO status  [01|02|03|04|91|92|93|94|95|FF XX XX XX JP], JP < 0x1C
        #00  read signal buffer        [00 NN ...]
        #01  write signal buffer       [01 NN ...]  NN < 0x33
        #02  STATUS_SIGNAL             [02 XX XX XX JP], ACK: [12 06 A0 HI LO]
        #03  STATUS_MOTORDREHZAHL      ACK: [12 1D A0 RPM VS TPS MAFHI MAFLO V_TIA V_TCO ...]
        #04  STATUS_DIGITAL            ACK: [12 07 A0 SD SD1 SD2]
        #91  STATUS_ADD                ACK: [12 0C A0 ...]
        #92  STATUS_X                  ACK: [12 08 A0 HI LO HI LO]
        #93  STATUS_X (knock corr.?)   ACK: [12 05 A0 XX]  XX < 0x81
        #94  STATUS_1_OR_2_KAT         ACK: [12 05 A0 XX]
        #95  STATUS_X                  ACK: [12 0C A0 ...]
        #FF  close
0C  unknown
0D  (ROOT) read the AIF/VIN and other info fields,  ACK: [12 49 A0 ...]
14  read the error memory
21  read unknown value,                             ACK: [12 05 A0 NN]
22  reset evap [01..05],                            ACK: [12 05 A0 XX]  XX=00 ok, 01 already init
23  reset evap [01..05],                            ACK: [12 04 A0]
24  read the error memory
25  read coding status,                             ACK: [12 06 A0 ST NN]
2B  STATUS_SYSTEMCHECK_LAUFUNRUHE [89|01..05 00|01|02], ACK: A0, B0
31  test program download [00|06|02|03|0F SG HI LO NN ...], ACK: A0, A2
32  test program start
40  read unknown value [01|02],                     ACK: [12 05 A0 NN], B0
41  set  unknown value [01|02 NN],                  ACK: [12 04 A0], B0, A2
42  rewrite TI_AD_ADD_MMV_1/2 to chip [01|02],      ACK: [12 0A A0 03 00 00 00 01 01], B0
43  reset adaptations [BM BF],                      ACK: A0
53  read ID_HW_NR, ISN, DATE, VERSION, SERIALCODE,  ACK: [12 3E A0 ...]
90  (ROOT) service command, read/write-mode enable + baudrate [BR S E R I A L C O D E ...],
        ACK: A0, A1, A2, B0
9E  diagnostic mode enable and wait tester
9F  diagnostic mode end
```

RomRaider's own constant table (independent confirmation of `00`, `06 00`, `0B 00/01/02`, `43`):
<https://github.com/RomRaider/RomRaider/blob/master/src/main/java/com/romraider/io/protocol/ds2/iso9141/DS2Protocol.java>

```java
private static final byte[] READ_MEMORY_COMMAND    = new byte[]{0x06, 0x00};
private static final byte[] READ_PROCEDURE_COMMAND = new byte[]{0x0B, 0x02};
private static final byte[] ECU_INIT_COMMAND       = new byte[]{0x00};
private static final byte[] ECU_RESET_COMMAND      = new byte[]{0x43};
private static final byte[] SET_ADDRESS_COMMAND    = new byte[]{0x0B, 0x01};
private static final byte[] READ_ADDRESS_COMMAND   = new byte[]{0x0B, 0x00};
public  static final byte   VALID_RESPONSE         = (byte) 0xA0;
public  static final int    RESPONSE_NON_DATA_BYTES = 4;
```
[high]

garagediag's independent confirmation of `00`, `04`, `05`, `07`, `08`:
<https://github.com/tooming/garagediag/blob/main/ds2_diag.py>
```python
def ident(self, addr):  return self.request(addr, [0x00], timeout=0.4)
def faults(self, addr): return self.request(addr, [0x04], timeout=0.8)
def clear(self, addr):  return self.request(addr, [0x05], timeout=1.5)
def read_coding(self, addr):  return self.request(addr, [0x08], timeout=0.5)
def write_coding(self, addr, b): return self.request(addr, [0x07] + list(b), timeout=1.0)
```
[medium] — note `0x07`/`0x08` as *coding* read/write is garagediag's body-module usage; on the MS41
DME `0x07` is the generic memory-write command (see table above). Do not assume they are the same
semantics on the DME.

### 4.2 Identification — command `0x00`

Request: `12 04 00 16` [high]

Response: `12 <len> A0 <ident bytes...> <cks>`. The first 7 payload bytes are the **7-character
ASCII ECU ID** (e.g. `1429861`, `1406464`, `7519308`). [medium]
Evidence: the Arduino sketch pulls `c1..c7` from offsets 7..13 of a buffer whose first 4 bytes are
the request echo, i.e. payload bytes 0..6 of the response, and prints them as the "Ecu id"
<https://www.romraider.com/forum/viewtopic.php?f=58&t=16660>; the Logger.S `ecus.json` definition
format keys definitions on those same 7-character strings ("up to 7 characters max!")
<https://www.ms4x.net/index.php?title=Logger.S>.

Known MS41-family ECU IDs seen in definition files: `1405854, 1406464, 1429373, 1429861, 1432401,
1437806, 1440176` (MS41 class) and `1429764, 1430844, 7526753, 7500255, 7511570, 7519308, 7545150,
7551615` (MS42/MS43 class). [medium] <https://www.ms4x.net/index.php?title=Logger.S>

### 4.3 Read DTCs — command `0x04`

Two observed forms:

* **`12 04 04 <cks>`** — bare read-fault-memory, used by garagediag against any module. [medium]
  <https://github.com/tooming/garagediag/blob/main/ds2_diag.py>
* **`12 05 04 01 12`** — with sub-byte `0x01`, used by the working MS41 Arduino logger.
  (`0x12^0x05^0x04^0x01 = 0x12`.) [medium]
  <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660>

Response layout: `12 <len> A0 <count> <entry0...> <entryN> <cks>` — i.e. **payload byte 0 is the
number of stored faults**, followed by fixed-size entries. [medium]

* Arduino sketch: `errors = DS2data[8];` — with the 5-byte echo of `12 05 04 01 12` ahead of
  `12 <len> A0 <count>`, index 8 is exactly the first payload byte.
* garagediag `show_faults()`:
  ```python
  n = data[0]; rest = data[1:]
  if n and rest and len(rest) % n == 0:
      size = len(rest) // n            # entry size varies per ECU
      e = rest[k*size:(k+1)*size]
      code = e[0]                      # fault code (decimal index into the DTC table)
      art  = e[1]                      # fault type byte; high bits = present/stored flags
  ```
  — so entry size is **not fixed across modules**; derive it as `(len(payload)-1)/count`. [medium]
* `data[0] == 0` ⇒ no faults stored. [medium] garagediag.

**DTC code numbering**: MS41/MS42/MS43 fault codes are plain decimal indexes 1–255 into a BMW table
(1 = "Ignition coil Cyl 2", 8 = "Air Flow Meter (HFM)", 83 = "Crankshaft Sensor", 238–243 = "Misfire
Cyl 1..6", etc.). The full table is at
<https://sites.google.com/site/openms41/reverse-engineering/documentation/diagnostic-trouble-codes-dtc>
and is shipped as `ms41_dtc.json` in garagediag
(<https://github.com/tooming/garagediag/blob/main/ms41_dtc.json>). These are **not** SAE P-codes.
[high]

Commands `0x14` and `0x24` are also listed as "read the error memory" variants on MS41 — presumably
different filters (present vs stored). Unverified. [low]

### 4.4 Clear DTCs — command `0x05`

* `12 04 05 13` (garagediag's `clear`, `0x12^0x04^0x05 = 0x13`). [medium]
* mrf582 quotes the MS41 clear sequence as **`12 04 05`** + checksum.
  <https://www.romraider.com/forum/viewtopic.php?p=107273#p107273> [medium]
* Allow ≥1.5 s for the response. [medium] garagediag.

### 4.5 Read memory — command `0x06`

**Exact wire format** (from the MS41 disassembly, confirmed against an EDIABAS `AIF_LESEN` trace):

```
12   LEN   06   MODE   SEG   HI   LO   CNT   CKS
|    |     |    |      |     |    |    |
|    |     |    |      |     +----+----|------ 16-bit address, big-endian (HI then LO)
|    |     |    |      +----------------------- segment / address high byte (<3 => DPP0)
|    |     |    +------------------------------ 00 = read   (anything else => ACK 0xB0)
|    |     +----------------------------------- command 0x06 (T_DATA)
|    +----------------------------------------- total frame length = 0x09
+---------------------------------------------- DME address
                                           CNT = number of bytes to read, < 0xFD (table says < 0xF9)
```
[high] — d_munter: "format is: ECU | LEN | 06 (T_DATA) | 00 (00 for read, else ack=B0!!!) | SEG
(<3 = DPP0) | HI | LO | CNT (<FDh !!!) | CRC"
<https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=30>

So the address is a **24-bit big-endian value split SEG:HI:LO**, i.e. `address >> 16`, `>> 8`,
`& 0xFF`. A frequent error (made in the thread itself) is to send it little-endian — `12 09 06 03 00
A2 EF 02 51` is **wrong**; the correct frame for 2 bytes at `0xEFA2` is
`12 09 06 00 00 EF A2 02 <cks>`. [high]

Verified examples:

| Purpose | Request | Notes |
|---|---|---|
| Read 0xC8 bytes of AIF/VIN at `0x001D07` | `12 09 06 00 00 1D 07 C8 <cks>` → `12 CC A0 20 2D C3 16 24 30 C8 85 ...` | [high] d_munter, with the data matching offset 0x1D07 of a full ROM read |
| Read 13 bytes at `0x001D07` | `12 09 06 00 00 1D 07 0D 0A` | [medium] |
| Read knock map at `0x00D840`, 0x40 bytes | `12 09 06 00 00 D8 40 40 C5` | [high] real log line `SND [Read]: 1209060000D84040C5` <https://www.romraider.com/forum/viewtopic.php?p=107273#p107273> |
| …`0xD880` / `0xD8C0` / `0xD900` / `0xD940` | `...D8 80 40 05`, `...D8 C0 40 45`, `...D9 00 40 84`, `...D9 40 40 C4` | [high] same log |
| Read MAF at `0x00DA34`, 2 bytes | `12 09 06 00 00 DA 34 02 <cks>` | [medium] |
| Knock sensors block at `0x00DA63`, 7 bytes | `12 09 06 00 00 DA 63 07 A3` | [medium] Arduino sketch; response bytes 4..9 = per-cylinder knock × 0.2 |

Response: `12 <len> A0 <CNT data bytes> <cks>`. [high]

RomRaider builds the same thing: `buildRequest(READ_MEMORY_COMMAND /*06 00*/, {numBytes}, address)`
— note the byte count goes **last**, after the address. [high] `DS2Protocol.java`

Full-ROM read: the MS41 address space is 256 kB; RomRaider's Test App reads
`address: 000000, Length: 262144` by chunking into ≤0xFD-byte reads.
[medium] <https://romraider.com/forum/viewtopic.php?f=42&start=0&t=11086>

### 4.6 Write memory — command `0x07`

```
12 LEN 07 <06|02|0F> SEG HI LO NN <NN data bytes> CKS
ACK: [12 0A A0 <06|02|0F> HH+ MM+ LL+ NN <status>]   or A2 / B0
```
[low–medium] d_munter. Write access generally requires the service/unlock command `0x90` with a
serial code first; MS41 ROMs ship with write access disabled unless patched (see OpenMS41
"Enable Write Access"). **Do not implement blind writes.**

### 4.7 Status / live-data group reads — command `0x0B`

#### `0B 03` — STATUS_MOTORDREHZAHL, the main 17-parameter block

Request: `12 05 0B 03 1F`
Response: `12 1D A0 <25 data bytes> <cks>` (0x1D = 29-byte frame). [high]

Real response: `12 1D A0 07 56 00 2B 11 4F 8C 36 6C 01 C1 00 F8 74 AA 27 8B 80 00 80 00 34 34 C3 C3 17`
(dschultz, <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=45>)

Payload offsets (0 = first byte after `A0`), from the working Arduino decoder
<https://www.romraider.com/forum/viewtopic.php?f=58&t=16660> and cross-checked against
pBmwScanner's `ms41.py` <https://github.com/gigijoe/pBmwScanner/blob/master/ms41.py> and
d_munter's field order — **[medium]**:

| Off | Size | Field | Conversion |
|---|---|---|---|
| 0 | 2 | Engine speed | raw, 1/min |
| 2 | 1 | Vehicle speed | raw, km/h |
| 3 | 1 | Throttle position | `raw*100/255` % (pBmwScanner uses `raw*0.47`) |
| 4 | 2 | Engine load (MAF) | `raw*0.021` mg/stroke |
| 6 | 1 | Intake air temp (raw ADC/4) | `103.4 - raw*0.458` °C (pBmwScanner: `raw*(-0.458)+108`) |
| 7 | 1 | Coolant temp (raw ADC/4) | `108 - raw*0.45` °C |
| 8 | 1 | Ignition timing | `raw*0.373 - 23.6` °BTDC |
| 9 | 2 | Injector pulse width | `raw*0.00534` ms |
| 11 | 2 | IACV duty | `raw*0.00153` % |
| 13 | 2 | (unknown) | |
| 15 | 1 | VANOS angle | `raw*0.3745` KW degrees |
| 16 | 1 | Battery voltage | `raw*0.10196` V (Logger.S uses `0.1015625`) |
| 17 | 2 | Lambda integrator 1 | `raw - 32768` |
| 19 | 2 | Lambda integrator 2 | `raw - 32768` |
| 21 | 1 | Lambda heater 1 (pre-cat B1) | `raw*0.3906` % |
| 22 | 1 | Lambda heater 2 (pre-cat B2) | `raw*0.3906` % |
| 23 | 1 | Lambda heater 3 (post-cat B1) | `raw*0.3906` % |
| 24 | 1 | Lambda heater 4 (post-cat B2) | `raw*0.3906` % |

Caution: the Arduino decoder indexes a buffer that still contains `12 1D A0`, so its `DS2data[3]` =
payload offset 0. The table above is already normalised to payload offsets. Temperature values are
the **raw 10-bit ADC/4**, not degrees — the DME sends the sensor voltage and INPA applies the sensor
transfer function, which is why the published °C formulas disagree slightly. [medium]
<https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=60>

#### `0B 04` — STATUS_DIGITAL (3 bitmask bytes)

Request `12 05 0B 04 18`; response `12 07 A0 B0 B1 B2 <cks>` (observed: `12 07 A0 21 00 01 95`).
[high] trace in <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=15>

Bit meanings, from d_munter <https://www.romraider.com/forum/viewtopic.php?p=107273#p107273>
[medium]:

```
B0: bits1-0  00=?, 01 Closed throttle, 10 Part load, 11 Full load
    0x04 S_ASC torque reduction request     0x08 S_MSR engine drag torque reduction
    0x10 S_GS gear-shift torque reduction   0x20 S_DWA theft deterrent
    0x40 S_AC air conditioning (high load)  0x80 S_KO compressor ON
B1: 0x01 S_CAN                              0x02 S_GE generator
    0x04 S_FS (AT: drive engaged)           0x08 LV_ST engine state "Start"
    0x10 LV_AE acceleration enrichment      0x20 LV_PUC overrun fuel cut
    0x40 S_REG1                             0x80 S_REG2
B2: 0x01 S_EKP electric fuel pump           0x02 S_KO_REL compressor relay
    0x04 S_VANOS                            0x08 S_KLAPPE exhaust flap
    0x10 S_RUN_LOSSES                       0x20 S_AAV tank ventilation valve
    0x40 S_SLP secondary air pump           0x80 S_SLV secondary air valve
```

#### `0B 02 0E` — STATUS_SIGNAL, single raw ADC channel

Request form: `12 09 0B 02 0E 00 00 <JP> <cks>` where `JP < 0x1C` is the "procedure number".
Response: `12 06 A0 HI LO <cks>` — a 10-bit raw value in `0x0000–0x03FF`,
volts = `raw * 5/1024`. [high] (d_munter gives the firmware jump-table disassembly; a trace shows
`12 09 0B 02 0E 00 00 01` → `12 06 A0 00 FA 4E` decoded by INPA as 4.825 V.)

Known procedure numbers [medium], <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=45>
and the Arduino sketch:

| JP | Signal | Example full frame |
|---|---|---|
| 0x01 | Lambda 1 (pre-cat B1) | `12 09 0B 02 0E 00 00 01 1D` |
| 0x02 | Lambda 2 (pre-cat B2) | `12 09 0B 02 0E 00 00 02 1E` |
| 0x04 | TPS volts | `12 09 0B 02 0E 00 00 04 18` |
| 0x05 | ? | `12 09 0B 02 0E 00 00 05 19` |
| 0x06 | MAF volts | `12 09 0B 02 0E 00 00 06 1A` |
| 0x07 | ? | `12 09 0B 02 0E 00 00 07 1B` |
| 0x17–0x1B | ? (further ADC channels) | |

The `0E 00 00` middle bytes appear to be don't-cares in the firmware ("i can not find parsing for
00 00 00 numbers here, so it could be any"); RomRaider calls the 3-byte form "legacy ADC def
0x0B020E support" and pads a `0x00` for it. [medium]

#### `0B 91` — STATUS_ADD, the adaptation block

Request `12 05 0B 91 8D`; response `12 0C A0 ...` (12-byte frame → 8 payload bytes). Decoded by the
Arduino logger as four big-endian words, each `value - 32768`: [medium]

```
payload[0:2] additive bank 1   payload[2:4] additive bank 2
payload[4:6] multiplicative b1 payload[6:8] multiplicative b2
```
<https://www.romraider.com/forum/viewtopic.php?f=58&t=16660>

#### `0B 93` — global knock retard

Request `12 05 0B 93 8F`; response `12 05 A0 XX <cks>`, value `(XX - 128) * 0.375` degrees.
[medium] Arduino sketch + d_munter (`XX < 0x81 knock correction variable(?)`).

#### `0B 01` / `0B 00` — arm a custom address list, then stream it

This is the fast multi-parameter mechanism RomRaider uses:

```
arm:   12 <len> 0B 01 <N> [<type> <a31..a24> <a23..a16> <a15..a8> <a7..a0>] * N  <cks>
       type 0 = byte, 1 = word, 2 = ADC procedure (used when the "address" is < 0x1C)
       ack: A0
read:  12 05 0B 00 <cks>  ->  12 <len> A0 <values in list order> <cks>
```
[medium] — garagediag's `MS41Logger` docstring states this is "verified against RomRaider's DS2
support" <https://github.com/tooming/garagediag/blob/main/ds2_diag.py>, and RomRaider's
`SET_ADDRESS_COMMAND = {0x0B, 0x01}` / `READ_ADDRESS_COMMAND = {0x0B, 0x00}` plus the
`bb.write(content.length); // number of parameters` line in `buildRequest` match exactly.
Caveat from garagediag: on MS43 this mechanism returned garbage for non-ADC channels; the fixed
`0B 03` block was more reliable. [low]

### 4.8 Reset adaptations — command `0x43`

```
12 06 43 <BM> <BF> <cks>
```
`BM` and `BF` are additive bitmasks (you may OR them, e.g. `12 06 43 1C 03 <cks>`). [medium]
<https://www.romraider.com/forum/viewtopic.php?p=107273#p107273>

| Frame | Effect |
|---|---|
| `12 06 43 01 00` | Reset learned knock maps, all 6 cylinders (`0xD840`) and `KR_ADAP` (`0xE9D9`) = 0x80 |
| `12 06 43 02 00` | Reset idle speed adaptations (`0xE95B`=0x80, `0xE950/E952/E954`=0, `0xE906`=0x8000) |
| `12 06 43 04 00` | Reset fuel trims (`0xF028`, `0xF030`, `0xF0D4`, `0xF0DC`) |
| `12 06 43 08 00` | Reset TPS adaptation (`0xE8DE`) |
| `12 06 43 10 00` | Reset altitude correction `MAF_FAC_ALTI_MMV` (`0xEF5E`) |
| `12 06 43 20 00` | Reset camshaft edge adaptation (`0x02CD` → `0xE9EB`) |
| `12 06 43 40 00` | Reset fuel trim adaptation `T_DLY_AD_i` (`0xE998`) |
| `12 06 43 80 00` | Reset segment time adaptation `SEG_AD_[CYL]` (`0xF510`) |
| `12 06 43 00 01` | ? (CAT adaptation) |
| `12 06 43 00 02` | ? (RPM adaptation) |

RomRaider implements this as `ECU_RESET_COMMAND = {0x43}` plus a 2-byte reset code. [high]

Useful adaptation RAM addresses to read with `0x06` (all MS41.2 p/n 1406464, likely same on
MS41.1) [medium]:

```
0xD840,0xD880,0xD8C0,0xD900,0xD940,0xD980  learned knock maps, 16(RPM) x 4(load) bytes each,
                                           value = (x-128)*0.375
0xF028  fuel additive  bank 1   word, (x-32768)*0.004
0xF030  fuel mult.     bank 1   word, (x-32768)*(100/65536)
0xF0D4  fuel additive  bank 2   word, (x-32768)*0.004
0xF0DC  fuel mult.     bank 2   word, (x-32768)*(100/65536)
0xE8DE  TPS adaptation             word
```
<https://www.romraider.com/forum/viewtopic.php?p=107273#p107273>

### 4.9 Other commands worth knowing

* **`0x0D`** — read AIF/VIN info block, `ACK: [12 49 A0 ...]` (0x49 = 73-byte frame). [low]
* **`0x53`** — read `ID_HW_NR, ISN, DATE, VERSION, SERIALCODE`, `ACK: [12 3E A0 ...]`. [low]
* **ISN read via `0x00`**: EWSync reads the immobiliser ISN from the DME with the plain ident
  command and takes 4 BCD nibbles out of the reply, then writes it to the EWS at `0x44` with
  command **`0x61`**: `ds2_build_frame(0x44, [0x61, high, low])`. [low] — single source,
  <https://github.com/0xDevDav/EWSync/blob/master/ewssync.py>. The claim that the ISN comes back in
  the `0x00` ident reply is unusual; treat with suspicion.
* **`0x90`** — service/unlock, also sets the baud rate via a `BR` byte written into the SAB80C166
  `S0BG` register: `BR = (CPU_MHz*1e6)/(32*baud) - 1`, `BR <= 0x3F`, default `0x26`/`0x23`
  (~16400 bps); bit 6 (`0x40`) sets `S0BRS` (divide serial clock by an extra 2/3). [low]
  <https://www.romraider.com/forum/viewtopic.php?f=42&t=11086&start=45>
* **Baud switching on MS42/MS43** (not MS41): `12 08 91 00 96 00 00 1D` → 38400 baud.
  [low] <https://www.ms4x.net/index.php?title=Logger.S>
* **Component activation**: no documented DS2 actuator-test command for MS41 was found. `0x31`
  ("test program download") / `0x32` ("test program start") are the firmware's own labels and are
  the likely path, but no byte sequences are published. garagediag explicitly warns against blind
  probing of neighbouring command space because it overlaps coding writes. [low]

---

## 5. DS2 vs. KWP/ISO9141 on MS41, and the two connectors

* **20-pin round engine-bay connector** (E30/E34/E36/E38/E39/E46/Z3, ~1988–2000): carries the DS2
  K-line. Relevant pins: **14 = battery +12 V, 15 = L-line, 17 = K-line, 19 = GND, 20 = K-line**.
  [medium] <https://allpinouts.org/pinouts/connectors/car/obd-ii-bmw-vehicle-diagnostic/>
* **Wiring a 16-pin OBD-II plug to the round connector** (confirmed working for DS2/RomRaider):
  OBD pin 7 ↔ round pin 17 (K-line), OBD pin 5 ↔ round pin 19 (ground), OBD pin 16 ↔ round pin 14
  (+12 V). [high] dschultz, <https://www.romraider.com/forum/viewtopic.php?p=107273#p107273>
* **Bridging the cabin OBD-II port through to the DME**: on cars where the cabin socket is not wired
  to the DME K-line, "use a small piece of wire to connect pin 2 to pin 17 in the round connector to
  bridge the car's OBD-II port in the cabin through to the ECU." [medium] same source.
  A related MS41.0 recipe: remove pin 19 from the diagnostic port cap and bridge pin 15 to pin 20.
  [low] <https://povertybuilt.com/blogs/how-tos-for-tuning-bmws/how-to-flash-your-ms41-equipped-e36-e36-m3-z3-z3m-e39-528>
* **What the cabin OBD-II port speaks**: on E36 it is the ISO 9141-2 K-line on pin 7. For MS41.1 /
  MS41.2 (the OBD-II variants) the *same physical K-line* carries both the legislated ISO 9141
  OBD-II layer and BMW's DS2 layer — they are different protocols sharing the wire, distinguished by
  framing, not by pin. [medium] — combination of the pinout source above, the MG-Rover discussion
  "Access to DS2 Line as well as ISO9141 K Line"
  <https://www.mg-rover.org/threads/access-to-ds2-line-as-well-as-iso9141-k-line.414121/>, and the
  RomRaider thread where a user asks whether their E36 K-line is "OBD2 ISO9141-2 or something else"
  and is told INPA/RomRaider use DS2 on the same line
  <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660>.
* **MS41 variants**: **MS41.0 is OBD-I; MS41.1 / MS41.2 are OBD-II.** MS41.1 = M52 in E36 328i
  (1996–99); MS41.2 = S52 (Z3M etc.). [medium]
  <https://www.r3vlimited.com/board/forum/e30-technical-forums/24v-engine-swaps/m50-52-s50-52/9977752-ms41-software-versions-archive>,
  RomRaider thread discussion of "MS 41.1 fuer M52 OBD II" as the INPA ECU selection.
* **Generic OBD-II PIDs on MS41**: "OBD2 Mode 1 (live data) is mostly implemented" on MS41.1/.2, but
  the 5-baud ISO 9141 init and Mode-01 PID coverage are incomplete/quirky; nobody in the sources
  recommends generic scan tools for anything beyond emissions readiness. [low] — weakly sourced, see
  §7. An ELM327 will talk the ISO 9141 OBD-II layer but **not** DS2; a plain FTDI KKL cable is
  required for DS2. [high]
  <https://github.com/tooming/garagediag> ("An ELM327 will *not* work with this tool"),
  <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660>.
* **Cable**: the community-standard cable for MS41 DS2 work is a **VAG-COM KKL with an FT232 chip**
  (the ~€15 "INPA cable" / K+DCAN). [high]
  <https://www.romraider.com/forum/viewtopic.php?p=107273#p107273>, garagediag README.
* **Other variants on the family**: EDIABAS/INPA knows at least four MS41 DS2 SGBD variants
  (`MS410DS1`, `MS411DS1`, `MS41xDS0..DS3`). The `.PRG`/`.BIV` SGBD files are the ground truth for
  job → byte-sequence mapping and are worth obtaining. [medium] RomRaider thread page 1.

---

## 6. Open-source implementations worth studying

| Project | URL | What's in it |
|---|---|---|
| **RomRaider** (Java) | <https://github.com/RomRaider/RomRaider/tree/master/src/main/java/com/romraider/io/protocol/ds2/iso9141> | The most complete open DS2 client. `DS2Protocol.java` has the command constant table, `buildRequest`, and the 9600/8/E/1 connection properties; `DS2ResponseProcessor.java` has frame validation and `RESPONSE_NON_DATA_BYTES = 4`; `DS2LoggerConnection.java` dispatches on group prefixes `0x0b0x00..0x0b0x95` and `0x060x00`. |
| **EdiabasLib** (C#) | <https://github.com/uholeschak/ediabaslib/blob/master/EdiabasLib/EdiabasLib/EdInterfaceObd.cs> | `case 0x0006: // DS2` sets even parity, length-at-offset-1, DTR, interbyte time; `TransDs2` / `TelLengthDs2` / `CalcChecksumXor` are the reference transport implementation incl. echo handling and regen-time pacing. `EdFtdiInterfaceAndroid.cs` for FTDI latency handling. |
| **garagediag** (Python, stdlib only) | <https://github.com/tooming/garagediag/blob/main/ds2_diag.py> | Closest to what you're building: DS2 class with resync-tolerant frame parser, module address map, fault read/clear/decode, `MS41Logger` with the `0B 01`/`0B 00` arm-and-stream mechanism, plus `ms41_dtc.json` and `ms41_ram_params.json` (RomRaider logger def v353, ECU 1429861). Also `docs/MODULES.md`. |
| **oleavr/bmw-coding `ds2.py`** (Python) | <https://github.com/oleavr/bmw-coding/blob/master/ds2.py> | 80-line minimal reference: framing, XOR, echo read, status-byte table (`0xA0/0xA1/0xA2/0xFF`), module constants `MOTRONIC/AT/IKE/LCM`. Good skeleton. |
| **opetany93/ds2-protocol** (Rust, `no_std`) | <https://github.com/opetany93/ds2-protocol> | Cleanest spec-like README of the frame format, plus a typed error model (`Timeout/Checksum/UnexpectedAddress/InvalidLength/CommandTooLong`) worth copying into Python exceptions. Has unit tests with encoded frames in `tests/`. |
| **handmade0octopus/ds2** (Arduino/ESP32) | <https://github.com/handmade0octopus/ds2> | The `DS2.h` header doc is the canonical short description of echo behaviour and the `A0`/`B0`/`FF` ack bytes; gives `ECU id - {0x12, 0x04, 0x00, 0x16}` and `General values - {0x12, 0x05, 0x0B, 0x03, 0x1F}` as literal constants. |
| **muki01/OBD2_KLine_Library** | <https://github.com/muki01/OBD2_KLine_Library/blob/main/src/KLine_Protocol.cpp> | A single `DS2_CONFIG` struct spelling out: 9600, `SERIAL_8E1`, `Checksum_XOR`, `Init_Ping`, header `{0x12}`, `Length_SeparateByte`, `lengthIncludesFrame = true`, and P1–P4/W1–W4 timings. Very handy as a cross-check. |
| **gigijoe/pBmwScanner** (Python) | <https://github.com/gigijoe/pBmwScanner/blob/master/ms41.py> | `ds2.py` is a near-copy of oleavr's; `ms41.py` has the full decode of the `0B 03` status block with scaling factors. (Note: its `p = reply[2:]` indexing is off by one relative to its own field comments.) |
| **0xDevDav/EWSync** (Python) | <https://github.com/0xDevDav/EWSync> | DME↔EWS ISN sync. README is a tidy restatement of the frame format; code gives `EWS_ADDRESS = 0x44` and `EWS_WRITE_ISN_CMD = 0x61`. Single-sourced claims — verify before trusting. |
| **RomRaider forum: "DS2 — datalogging MS41/42/43 by serial protocol"** | <https://romraider.com/forum/viewtopic.php?f=42&start=0&t=11086> (35 pages) | **The primary source for everything in §4.** d_munter's firmware-disassembly command table is on page 4 (`&start=45`); the memory-read wire format on page 3 (`&start=30`); adaptation resets and STATUS_DIGITAL bits on page 8 (`viewtopic.php?p=107273`); EDIABAS traces on pages 1–2. |
| **RomRaider forum: MS41.0 OBD port relocation / Arduino** | <https://www.romraider.com/forum/viewtopic.php?f=58&t=16660> | A complete working Arduino MS41 DS2 logger pasted inline: `SERIAL_8E1`, `ISORequestDelay = 112`, and literal request builders for ident, `0B 03`, `0B 91`, `0B 93`, `0B 02 0E xx`, `04 01` (DTC), and `06` memory reads, each with its precomputed checksum. |
| **MS4X wiki — Logger.S** | <https://www.ms4x.net/index.php?title=Logger.S> | JSON definition format with real DS2 addresses (`"0x12050B031F"`), field offsets/multipliers, ECU-ID lists, and the MS42/43 baud-switch command. (The wiki's own "BMW DS2 Serial Protocol" page is an empty stub containing only "asdf".) |
| **OpenMS41 site** | <https://sites.google.com/site/openms41/> | MS41 DTC number→text table, memory map, write-access notes. |
| **wilhelm-docs address table** | <https://github.com/piersholt/wilhelm-docs/blob/master/address.md> | The 8-bit BMW device address index (I/K/D bus) that the DS2 diagnostic addresses are drawn from. |
| **Google Sheet "DS2 Serial Commands"** | <https://docs.google.com/spreadsheets/d/1l7QOeayNgD6e2d99U2F5XZE8wlpgFHyvxOZdqfDqd1A/edit> | Referenced from the RomRaider thread as the consolidated command list. **Login-gated** — all export/gviz/pub URLs return Google's sign-in page. Worth opening manually in a browser; likely the single densest artefact available. |

---

## 7. Conflicts and open questions

1. **8E1 vs 8N1.** allpinouts.org states DS2 runs "9600 baud with 8-bit data, no parity, and one stop
   bit (8N1)" <https://allpinouts.org/pinouts/connectors/car/obd-ii-bmw-vehicle-diagnostic/>, and
   that phrasing has propagated into several search summaries. **Every implementation that actually
   talks to a car uses even parity** (RomRaider, EdiabasLib, oleavr, muki01, garagediag, the Arduino
   sketch). Verdict: **8E1**, high confidence; treat the 8N1 claim as an error. Still, make parity a
   CLI flag — receiving 8E1 data as 8N1 "works" byte-wise on many UARTs, so a mis-set parity can
   masquerade as intermittent corruption.
2. **`0xB0` status byte.** oleavr/pBmwScanner/garagediag enumerate only `A0/A1/A2/FF` and would raise
   "unknown status" on `0xB0`. handmade0octopus and the MS41 disassembly both treat `0xB0` as the
   generic negative response. Resolution: accept `0xB0` as a NAK; it is probably ECU-family-specific.
3. **`12 04 04` vs `12 05 04 01` for reading faults.** garagediag uses the bare form on all modules;
   the MS41 Arduino logger uses the `01` sub-byte. d_munter lists `04`, `14` and `24` all as "read
   the error memory". Unresolved: what the sub-byte selects (present vs stored vs clear-on-read?) and
   whether MS41 accepts the bare `12 04 04`. **Test both on the car.**
4. **Fault entry size.** garagediag deliberately derives entry size as `(payload_len - 1) / count`
   because it "varies per ECU". No source states the MS41 entry size. Unknown: whether MS41 entries
   are 1, 2 or 3 bytes, and the exact meaning of the second ("art"/type) byte's high bits.
5. **Memory-read byte-count limit.** d_munter's command table says `NN < 0xF9`; his wire-format post
   says `CNT (<FDh !!!)`. Use ≤0xF8 to be safe.
6. **`0x06` mode byte vs segment byte.** The format is `06 MODE SEG HI LO CNT` where MODE must be
   `0x00` for a read. Some posts in the thread collapse MODE and SEG and write "06 00 00 HI LO CNT",
   which happens to be identical for addresses below 0x10000. For MS41's 256 kB space you will need
   SEG ∈ {0,1,2,3}; d_munter notes "SEG (<3 = DPP0)" — the exact DPP/segment semantics above 0x03 are
   not documented.
7. **`0x07`/`0x08` semantics.** garagediag calls `0x07` "write coding" and `0x08` "read coding" for
   body modules; d_munter's MS41 table says `0x07` is generic memory write and does not list `0x08`
   at all. These are very likely different per module class. Do not send `0x07` to the DME casually.
8. **EWSync's ISN claim.** It reads the ISN from the ident response (`0x00`) and writes it to EWS
   with `0x61`. No corroborating source; d_munter attributes ISN to command `0x53`. Single-sourced;
   treat `0x61` as unverified and potentially destructive.
9. **MS41 generic OBD-II PID coverage.** Claims that "Mode 1 is mostly implemented" trace back to a
   forum paraphrase, not a tested PID list. Nobody has published a Mode-01 supported-PID bitmap for
   MS41.1. Open question — easy to resolve on the car with a 5-baud init + `01 00`.
10. **DTR.** EdiabasLib asserts DTR for DS2 but not DS1, with no explanation. Whether the FTDI KKL
    cable needs DTR asserted is cable-dependent. Unresolved; make it a flag.
11. **FTDI latency direction.** EdiabasLib raises latency to 50 ms "to prevent data loss"; the Linux
    community standard is to lower it to 1 ms for responsiveness. These optimise different things
    (USB transfer count vs latency). Unresolved for this specific use case — benchmark both.
12. **The "DS2 Serial Commands" Google Sheet** referenced by both the RomRaider thread OP and
    d_munter is not publicly readable. Its contents may supersede or contradict §4.
13. **No documented actuator/component activation for MS41.** `0x31`/`0x32` are labelled "test
    program download/start" in the firmware, but no concrete sequences exist in any public source.
14. **Temperature scaling disagreement.** `103.4 - raw*0.458` (Arduino) vs `108 - raw*0.458`
    (pBmwScanner) vs `108 - raw*0.45` (Arduino, coolant). All three are approximations of a sensor
    transfer curve applied to a raw ADC/4 value; the DME itself sends volts, not °C. Pick one,
    document it, and expose the raw value too.
