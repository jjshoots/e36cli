---
name: Profile request
about: Your ECU isn't recognized (generic-fallback warning) or lacks parameters
labels: profile
---

**`e36 ident` output** (paste the whole table):

```
(paste here)
```

**Car**: year, market (US/Euro/other), engine, transmission, known tune/swap
history.

**Capture file**: attach a session from `~/.local/share/e36cli/captures/`
covering `ident` + `dtc read` + `live --once` if you can — it lets us build
and regression-test the profile without your car. (It contains your ECU's
serial/ident strings; check before posting.)

**Live plausibility** (optional but gold): with the engine idling, do
coolant/RPM/battery values look physically right? Does blipping the throttle
move RPM + throttle + MAF together?
