"""`e36` command-line interface. Command surface is fixed by SPEC.md."""

from __future__ import annotations

import csv
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import dtc as dtcmod
from . import ds2, live, ms41
from .capture import CaptureWriter, default_capture_dir, list_sessions
from .doctor import hard_failure, run_checks
from .sim import SimDtc, SimTransport, SimulatedDME
from .transport import SerialTransport, Transport, TransportError

app = typer.Typer(
    name="e36",
    help="BMW E36 (MS41) DS2 diagnostics over K-line.",
    no_args_is_help=True,
    add_completion=False,
)
dtc_app = typer.Typer(help="Fault codes.", no_args_is_help=True)
app.add_typer(dtc_app, name="dtc")

console = Console()
err_console = Console(stderr=True)

CAPTURE_DIR_ENV = "E36CLI_CAPTURE_DIR"


@dataclass
class Config:
    port: str = "/dev/ttyUSB0"
    sim: bool = False
    sim_fixture: Optional[Path] = None
    profile_id: Optional[str] = None
    timing_debug: bool = False

    @property
    def capture_dir(self) -> Path:
        env = os.environ.get(CAPTURE_DIR_ENV)
        return Path(env) if env else default_capture_dir()


@app.callback()
def main(
    ctx: typer.Context,
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial device."),
    sim: bool = typer.Option(False, "--sim", help="Simulated DME instead of hardware."),
    sim_fixture: Optional[Path] = typer.Option(
        None, "--sim-fixture", help="Replay a capture JSONL (implies --sim)."
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Override profile auto-match."),
    timing_debug: bool = typer.Option(False, "--timing-debug", help="Latency stats to stderr."),
) -> None:
    ctx.obj = Config(
        port=port,
        sim=sim or sim_fixture is not None,
        sim_fixture=sim_fixture,
        profile_id=profile,
        timing_debug=timing_debug,
    )


def make_transport(cfg: Config) -> Transport:
    capture = CaptureWriter("sim" if cfg.sim else cfg.port, cfg.capture_dir)
    if cfg.sim:
        if cfg.sim_fixture is not None:
            sim = SimTransport.from_capture(cfg.sim_fixture)
            sim._capture = capture
            return sim
        # E36CLI_SIM_DTCS="100,214" seeds fault codes into the simulated DME
        # (demos and CLI tests; the sim has no other way in from the CLI).
        codes = os.environ.get("E36CLI_SIM_DTCS", "")
        try:
            dtcs = [SimDtc(code=int(c)) for c in codes.split(",") if c.strip()]
        except ValueError:
            raise fail(f"E36CLI_SIM_DTCS must be comma-separated integers, got {codes!r}") from None
        return SimTransport(SimulatedDME(dtcs=dtcs), capture=capture)
    return SerialTransport(cfg.port, capture=capture)


@contextmanager
def make_client(cfg: Config) -> Iterator[ds2.DS2Client]:
    """Open transport (+ always-on capture), close both on every exit path."""
    try:
        transport = make_transport(cfg)
    except TransportError as exc:
        raise fail(str(exc)) from None
    try:
        yield ds2.DS2Client(transport)
    finally:
        transport.close()


def fail(msg: str) -> "typer.Exit":
    err_console.print(f"[red]error:[/red] {msg}")
    return typer.Exit(code=1)


def resolve_profile(cfg: Config, client: ds2.DS2Client) -> tuple[ms41.Profile, ms41.Ident | None]:
    profiles = ms41.load_profiles()
    if cfg.profile_id is not None:
        try:
            return profiles[cfg.profile_id], None
        except KeyError:
            raise fail(
                f"unknown profile {cfg.profile_id!r}; available: {', '.join(sorted(profiles))}"
            ) from None
    resp = client.query(ds2.ADDR["DME"], ms41.CMD_IDENT)
    ident = ms41.parse_ident(resp.data)
    profile = ms41.match_profile(ident, profiles)
    if profile.id == ms41.GENERIC_PROFILE_ID:
        err_console.print(
            f"[yellow]warning:[/yellow] no profile matches ECU {ident.ecu_id!r}; "
            "using generic fallback (common params only)"
        )
    return profile, ident


WIRE_ERRORS = (
    ds2.DS2Error,
    TransportError,
    ms41.ProfileError,
    ms41.DecodeError,
    dtcmod.DtcError,
)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check port, permissions, FTDI latency timer, captures dir."""
    cfg: Config = ctx.obj
    checks = run_checks(cfg.port, cfg.capture_dir, sim=cfg.sim)
    table = Table(title="e36 doctor")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Detail", overflow="fold")
    for c in checks:
        table.add_row(c.name, "[green]✓[/green]" if c.ok else "[red]✗[/red]", c.detail)
    console.print(table)
    if hard_failure(checks):
        raise typer.Exit(code=1)


@app.command()
def ident(ctx: typer.Context) -> None:
    """Read and parse the DME identification; show the matched profile."""
    cfg: Config = ctx.obj
    try:
        with make_client(cfg) as client:
            profile, parsed = resolve_profile(cfg, client)
            if parsed is None:  # --profile override: still show the real ident
                resp = client.query(ds2.ADDR["DME"], ms41.CMD_IDENT)
                parsed = ms41.parse_ident(resp.data)
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    table = Table(title="DME identification")
    table.add_column("Field")
    table.add_column("Value")
    rows = [
        ("ECU ID", parsed.ecu_id),
        ("HW index", parsed.hw_index),
        ("Coding index", parsed.coding_index),
        ("Diag index", parsed.diag_index),
        ("Build week/year", f"{parsed.mfg_week}/{parsed.mfg_year}" if parsed.mfg_week else None),
        ("Supplier", parsed.supplier),
        ("SW index", parsed.sw_index),
        ("Serial", parsed.serial),
        ("ISN (EWS)", parsed.isn),
    ]
    for name, value in rows:
        if value is not None:
            table.add_row(name, str(value))
    table.add_row("Profile", f"{profile.id} — {profile.description}")
    console.print(table)


@app.command()
def scan(ctx: typer.Context) -> None:
    """Probe known E36 module addresses; list responders."""
    cfg: Config = ctx.obj
    probe = ds2.Timing(deadline=0.15, retries=0)
    table = Table(title="DS2 bus scan")
    table.add_column("Module")
    table.add_column("Addr")
    table.add_column("Response")
    found = 0
    with make_client(cfg) as client:
        for name, addr in sorted(ds2.ADDR.items(), key=lambda kv: kv[1]):
            try:
                resp = client.query(addr, b"\x00", timing=probe)
                table.add_row(name, f"0x{addr:02X}", f"ok ({len(resp.data)}B ident)")
                found += 1
            except ds2.NakResponse as exc:
                table.add_row(name, f"0x{addr:02X}", f"answers ({exc.meaning})")
                found += 1
            except WIRE_ERRORS:
                table.add_row(name, f"0x{addr:02X}", "[dim]silent[/dim]")
    console.print(table)
    console.print(f"{found} module(s) responding")


@dtc_app.command("read")
def dtc_read(ctx: typer.Context) -> None:
    """Read and decode stored fault codes."""
    cfg: Config = ctx.obj
    hours_now: float | None = None
    try:
        with make_client(cfg) as client:
            try:
                resp = client.query(ds2.ADDR["DME"], ms41.CMD_DTC_READ, timing=ds2.SLOW)
            except ds2.NakResponse:  # some variants want the bare form (research §4)
                resp = client.query(ds2.ADDR["DME"], ms41.CMD_DTC_READ_BARE, timing=ds2.SLOW)
            faults = dtcmod.decode_dtc_response(resp.data)
            if faults and any(f.hours_raw is not None for f in faults):
                try:  # prepare command returns the current operating-hours counter
                    prep = client.query(ds2.ADDR["DME"], ms41.CMD_DTC_PREPARE, timing=ds2.SLOW)
                    hours_now = dtcmod.decode_hours_counter(prep.data)
                except WIRE_ERRORS:
                    hours_now = None  # fault ages are a bonus, not a requirement
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    if not faults:
        console.print("[green]No stored fault codes.[/green]")
        return
    table = Table(
        title=f"{len(faults)} stored fault(s)",
        caption="? = description not verified on this car",
    )
    table.add_column("Code", justify="right")
    table.add_column("Description")
    table.add_column("System")
    table.add_column("Freq", justify="right")
    if hours_now is not None:
        table.add_column("Age (h)", justify="right")
    table.add_column("Flags")
    for f in faults:
        row = [
            str(f.code),
            f.description if f.verified else f"{f.description} ?",
            f.system,
            "" if f.frequency is None else str(f.frequency),
        ]
        if hours_now is not None:
            age = f.hours_ago(round(hours_now / 0.1))
            row.append("" if age is None else f"{age:.1f}")
        row.append(", ".join(f.flags))
        table.add_row(*row)
    console.print(table)


@dtc_app.command("clear")
def dtc_clear(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Clear fault memory (WRITE operation)."""
    cfg: Config = ctx.obj
    if not yes and not typer.confirm("Clear the DME fault memory?"):
        console.print("Aborted.")
        raise typer.Exit(code=1)
    try:
        with make_client(cfg) as client:
            client.query(ds2.ADDR["DME"], ms41.CMD_DTC_CLEAR, timing=ds2.CLEAR)
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    console.print("[green]Fault memory cleared.[/green]")


@app.command("live")
def live_cmd(
    ctx: typer.Context,
    once: bool = typer.Option(False, "--once", help="Single snapshot, then exit."),
    json_out: bool = typer.Option(False, "--json", help="Single snapshot as JSON."),
    rate: float = typer.Option(10.0, "--rate", help="Max poll rate (Hz)."),
    all_params: bool = typer.Option(False, "--all", help="Every profile param (default: core set)."),
    params: Optional[str] = typer.Option(None, "--params", help="Comma-separated param names."),
) -> None:
    """Live dashboard of the core parameter set (default), or one snapshot.

    Defaults to the profile's dashboard-core subset for a usable refresh rate
    on the 9600-baud wire; --all reads everything, --params picks names.
    """
    cfg: Config = ctx.obj
    stats = live.TimingStats() if cfg.timing_debug else None
    try:
        with make_client(cfg) as client:
            profile, _ = resolve_profile(cfg, client)
            names = live.select_names(profile, all_params, params)
            if once or json_out:
                reads = live.plan(profile, names=names)
                values = live.poll_once(client, profile, reads, stats=stats)
                if json_out:
                    doc = {
                        "profile": profile.id,
                        "params": {
                            v.name: {
                                "value": v.value,
                                "unit": v.unit,
                                "raw": v.raw,
                                "verified": v.verified,
                            }
                            for v in values.values()
                        },
                    }
                    console.print_json(json.dumps(doc))
                else:
                    table = Table(
                        title=f"e36 snapshot — {profile.id}", caption="? = not verified on car"
                    )
                    table.add_column("Param")
                    table.add_column("Value", justify="right")
                    table.add_column("Unit")
                    for spec in profile.params:
                        v = values.get(spec.name)
                        if v is not None:
                            table.add_row(spec.label, live.format_value(v), v.unit)
                    console.print(table)
            else:
                live.run_dashboard(client, profile, console, rate=rate, stats=stats, names=names)
    except live.LiveFatal as exc:
        raise fail(str(exc)) from None
    except KeyError as exc:
        raise fail(f"unknown param: {exc}") from None
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    finally:
        if stats is not None:
            err_console.print(stats.summary())


@app.command("log")
def log_cmd(
    ctx: typer.Context,
    out: Path = typer.Argument(..., help="Output file (.csv or .jsonl)."),
    rate: float = typer.Option(10.0, "--rate", help="Max sample rate (Hz)."),
    samples: int = typer.Option(0, "--samples", help="Stop after N samples (0 = until Ctrl-C)."),
    all_params: bool = typer.Option(False, "--all", help="Every profile param (default: core set)."),
    params: Optional[str] = typer.Option(None, "--params", help="Comma-separated param names."),
) -> None:
    """Stream samples to CSV/JSONL until Ctrl-C (or --samples).

    Unverified params are marked: CSV column headers get a '?' suffix; JSONL
    rows carry a per-param "verified" field (SPEC invariant 3).
    """
    cfg: Config = ctx.obj
    stats = live.TimingStats() if cfg.timing_debug else None
    as_csv = out.suffix.lower() == ".csv"
    min_period = 1.0 / rate if rate > 0 else 0.0
    written = 0
    try:
        with make_client(cfg) as client:
            profile, _ = resolve_profile(cfg, client)
            selected = live.select_names(profile, all_params, params)
            reads = live.plan(profile, names=selected)
            specs = [p for p in profile.params if selected is None or p.name in selected]
            names = [p.name for p in specs]
            with out.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh) if as_csv else None
                if writer:
                    writer.writerow(
                        ["t", *(p.name if p.verified else f"{p.name}?" for p in specs)]
                    )
                t0 = time.monotonic()
                while samples <= 0 or written < samples:
                    start = time.monotonic()
                    values = live.poll_once(client, profile, reads, stats=stats)
                    t = time.monotonic() - t0
                    if writer:
                        writer.writerow(
                            [f"{t:.3f}"] + [
                                f"{values[n].value:.4g}" if n in values else "" for n in names
                            ]
                        )
                    else:
                        fh.write(
                            json.dumps(
                                {
                                    "t": round(t, 3),
                                    "params": {
                                        n: {"value": v.value, "verified": v.verified}
                                        for n, v in values.items()
                                    },
                                }
                            )
                            + "\n"
                        )
                    written += 1
                    leftover = min_period - (time.monotonic() - start)
                    if leftover > 0:
                        time.sleep(leftover)
    except KeyboardInterrupt:
        pass
    except KeyError as exc:
        raise fail(f"unknown param: {exc}") from None
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    finally:
        if stats is not None:
            err_console.print(stats.summary())
    console.print(f"Wrote {written} sample(s) to {out}")


@app.command()
def raw(
    ctx: typer.Context,
    hexbytes: list[str] = typer.Argument(..., help="Frame or addr+payload, hex bytes."),
) -> None:
    """Send an arbitrary DS2 frame; print the hex response (the probe tool).

    Accepts either a complete frame (len+checksum validated) or bare
    `ADDR PAYLOAD...` — the frame is then built for you.
    """
    cfg: Config = ctx.obj
    try:
        data = ds2.parse_hex(" ".join(hexbytes))
    except ds2.DS2Error as exc:
        raise fail(str(exc)) from None
    if len(data) < 1:
        raise fail("need at least an address byte")
    try:
        frame = ds2.parse_frame(data)
        addr, payload = frame.addr, frame.payload
    except ds2.DS2Error:
        addr, payload = data[0], bytes(data[1:])
    request = ds2.build_frame(addr, payload)
    console.print(f"TX  {ds2.hexstr(request)}")
    try:
        with make_client(cfg) as client:
            resp = client.query(addr, payload, timing=ds2.SLOW)
    except ds2.NakResponse as exc:
        console.print(f"RX  status 0x{exc.status:02X} ({exc.meaning})")
        raise typer.Exit(code=1) from None
    except WIRE_ERRORS as exc:
        raise fail(str(exc)) from None
    console.print(f"RX  {ds2.hexstr(resp.frame.raw)}")
    console.print(f"    status 0x{resp.status:02X}, data: {ds2.hexstr(resp.data) or '(none)'}")


@app.command()
def captures(
    ctx: typer.Context,
    show: Optional[int] = typer.Option(None, "--show", help="Print events of session #N."),
) -> None:
    """List capture sessions (or show one's wire events with --show N)."""
    cfg: Config = ctx.obj
    sessions = list_sessions(cfg.capture_dir)
    if not sessions:
        console.print(f"No captures in {cfg.capture_dir}")
        return
    if show is not None:
        if not 1 <= show <= len(sessions):
            raise fail(f"session {show} out of range (1..{len(sessions)})")
        info = sessions[show - 1]
        from .capture import CaptureReader

        reader = CaptureReader(info.path)
        console.print(f"{info.path} — port {info.port}, started {info.started}")
        for ev in reader.events:
            console.print(f"{ev.t:.3f} {ev.dir}  {ds2.hexstr(ev.data)}")
        return
    table = Table(title=f"captures in {cfg.capture_dir}")
    table.add_column("#", justify="right")
    table.add_column("Started")
    table.add_column("Port")
    table.add_column("Events", justify="right")
    table.add_column("TX B", justify="right")
    table.add_column("RX B", justify="right")
    for i, s in enumerate(sessions, 1):
        table.add_row(str(i), s.started, s.port, str(s.n_events), str(s.bytes_tx), str(s.bytes_rx))
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
