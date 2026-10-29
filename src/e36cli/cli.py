"""`e36` command-line interface. Command surface is fixed by SPEC.md."""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ParamSpec, TypeVar

import typer
from rich.console import Console
from rich.table import Table

from . import dashboard as dashmod
from . import datalog, ds2, live, ms41, policy, writes
from . import dtc as dtcmod
from . import panel as panelmod
from .capture import (
    CaptureSink,
    CaptureWriter,
    KeepOpenCapture,
    default_capture_dir,
    list_sessions,
)
from .doctor import hard_failure, run_checks
from .sim import SimDtc, SimTransport, SimulatedDME
from .transport import (
    CapturingTransport,
    SerialTransport,
    Transport,
    TransportError,
    close_quietly,
)

P = ParamSpec("P")
R = TypeVar("R")

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
    sim_fixture: Path | None = None
    profile_id: str | None = None
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
    sim_fixture: Path | None = typer.Option(
        None, "--sim-fixture", help="Replay a capture JSONL (implies --sim)."
    ),
    profile: str | None = typer.Option(None, "--profile", help="Override profile auto-match."),
    timing_debug: bool = typer.Option(False, "--timing-debug", help="Latency stats to stderr."),
) -> None:
    ctx.obj = Config(
        port=port,
        sim=sim or sim_fixture is not None,
        sim_fixture=sim_fixture,
        profile_id=profile,
        timing_debug=timing_debug,
    )


def make_transport(cfg: Config, capture: CaptureSink | None = None) -> Transport:
    """The single transport factory: every transport it returns is captured
    (SPEC invariant 1). `capture` defaults to a fresh session file."""
    if capture is None:
        capture = CaptureWriter("sim" if cfg.sim else cfg.port, cfg.capture_dir)
    inner: Transport
    if cfg.sim:
        if cfg.sim_fixture is not None:
            inner = SimTransport.from_capture(cfg.sim_fixture)
        else:
            # E36CLI_SIM_DTCS="100,214" seeds fault codes into the simulated DME
            # (demos and CLI tests; the sim has no other way in from the CLI).
            codes = os.environ.get("E36CLI_SIM_DTCS", "")
            try:
                dtcs = [SimDtc(code=int(c)) for c in codes.split(",") if c.strip()]
            except ValueError:
                raise fail(
                    f"E36CLI_SIM_DTCS must be comma-separated integers, got {codes!r}"
                ) from None
            inner = SimTransport(SimulatedDME(dtcs=dtcs))
    else:
        inner = SerialTransport(cfg.port)
    return CapturingTransport(inner, capture)


@contextmanager
def make_client(cfg: Config) -> Iterator[ds2.DS2Client]:
    """Open transport (+ always-on capture), close both on every exit path.

    A close failure after another error is swallowed (STD-05): the user must
    see the error that got us here, not pyserial's complaint about a dead port.
    """
    try:
        transport = make_transport(cfg)
    except TransportError as exc:
        raise fail(str(exc)) from None
    try:
        yield ds2.DS2Client(transport)
    except BaseException:
        close_quietly(transport)
        raise
    transport.close()


def fail(msg: str) -> typer.Exit:
    err_console.print(f"[red]error:[/red] {msg}")
    return typer.Exit(code=1)


def user_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """The one place deliberate errors become a red line + exit 1 (STD-03).

    Anything that is not an E36Error is a bug and keeps its traceback.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except policy.USER_FACING as exc:
            raise fail(str(exc)) from None

    return wrapper


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
@user_errors
def ident(ctx: typer.Context) -> None:
    """Read and parse the DME identification; show the matched profile."""
    cfg: Config = ctx.obj
    with make_client(cfg) as client:
        profile, parsed = resolve_profile(cfg, client)
        if parsed is None:  # --profile override: still show the real ident
            resp = client.query(ds2.ADDR["DME"], ms41.CMD_IDENT)
            parsed = ms41.parse_ident(resp.data)
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
    # SPEC invariant 3: say it out loud when nothing in the matched profile has
    # ever been checked against a real car (scraped-only profiles). Scraped
    # descriptions already end in "(unverified)" — swap that for the louder
    # marker rather than printing both.
    desc = profile.description.removesuffix("(unverified)").rstrip()
    marker = (
        "" if any(p.verified for p in profile.params) else " [yellow](unverified profile)[/yellow]"
    )
    table.add_row("Profile", f"{profile.id} — {desc}{marker}")
    console.print(table)


# Euro E36 body modules historically need BMW's ADS interface (K-line as TXD,
# L-line as RXD) — a plain KKL cable may never reach them. See
# research/cluster-and-service-reset.md §2.0.
ADS_SUSPECTS = {"IKE", "ABS"}  # EWS 0x44 answers on KKL (car/captures/car-koeo-scan.jsonl)


@contextmanager
def _print_on_error(table: Table) -> Iterator[None]:
    """Show what was gathered before a fatal error ends the command."""
    try:
        yield
    except BaseException:
        console.print(table)
        raise


@app.command()
@user_errors
def scan(ctx: typer.Context) -> None:
    """Probe known E36 module addresses (read-only idents); list responders.

    Sends only the harmless ident request (cmd 0x00) to each address — never
    fault-clear or write jobs to non-DME modules.
    """
    cfg: Config = ctx.obj
    probe = ds2.Timing(deadline=0.15, retries=0)
    table = Table(
        title="DS2 bus scan",
        caption="idents from modules other than the DME are unverified on this car",
    )
    table.add_column("Module")
    table.add_column("Addr")
    table.add_column("Response")
    table.add_column("Ident bytes", overflow="fold")
    found = 0
    with make_client(cfg) as client, _print_on_error(table):
        for name, addr in sorted(ds2.ADDR.items(), key=lambda kv: kv[1]):
            try:
                resp = client.query(addr, b"\x00", timing=probe)
                shown = ds2.hexstr(resp.data[:32]) + ("…" if len(resp.data) > 32 else "")
                table.add_row(name, f"0x{addr:02X}", f"ok ({len(resp.data)}B ident)", shown)
                found += 1
            except ds2.NakResponse as exc:
                table.add_row(name, f"0x{addr:02X}", f"answers ({exc.meaning})", "")
                found += 1
            except policy.SCAN_SILENT:
                silent = (
                    "no answer (may require ADS interface)"
                    if name in ADS_SUSPECTS
                    else "[dim]silent[/dim]"
                )
                table.add_row(name, f"0x{addr:02X}", silent, "")
    console.print(table)
    console.print(f"{found} module(s) responding")


@dtc_app.command("read")
@user_errors
def dtc_read(ctx: typer.Context) -> None:
    """Read and decode stored fault codes."""
    cfg: Config = ctx.obj
    with make_client(cfg) as client:
        faults, hours_now = dtcmod.fetch_faults(client)
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
            age = dtcmod.age_hours(f, hours_now)
            row.append("" if age is None else f"{age:.1f}")
        row.append(", ".join(f.flags))
        table.add_row(*row)
    console.print(table)


@dtc_app.command("clear")
@user_errors
def dtc_clear(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Clear fault memory (WRITE operation)."""
    cfg: Config = ctx.obj
    if not yes and not typer.confirm(writes.CLEAR_QUESTION):
        console.print("Aborted.")
        raise typer.Exit(code=1)
    with make_client(cfg) as client:
        result = writes.clear_faults(client)
    if result.outcome is not writes.ClearOutcome.CLEARED:
        raise fail(result.message)
    console.print("[green]Fault memory cleared.[/green]")
    if result.faults:
        console.print(f"[yellow]{len(result.faults)} fault(s) re-stored immediately.[/yellow]")


@app.command("live")
@user_errors
def live_cmd(
    ctx: typer.Context,
    once: bool = typer.Option(False, "--once", help="Single snapshot, then exit."),
    json_out: bool = typer.Option(False, "--json", help="Single snapshot as JSON."),
    rate: float = typer.Option(10.0, "--rate", help="Max poll rate (Hz)."),
    all_params: bool = typer.Option(
        False, "--all", help="Every profile param (default: core set)."
    ),
    params: str | None = typer.Option(None, "--params", help="Comma-separated param names."),
    dtc_on: bool = typer.Option(
        True, "--dtc/--no-dtc", help="Also show stored faults (polled between live reads)."
    ),
    dtc_interval: float = typer.Option(
        10.0, "--dtc-interval", help="Seconds between fault polls in the dashboard."
    ),
) -> None:
    """Live dashboard of the core parameter set (default), or one snapshot.

    Defaults to the profile's dashboard-core subset for a usable refresh rate
    on the 9600-baud wire; --all reads everything, --params picks names.
    Stored faults are shown too (--no-dtc to skip); a failed fault read is
    never fatal — params still render.
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
                faults: list[dtcmod.Dtc] | None = None
                hours_now: float | None = None
                faults_error: str | None = None
                if dtc_on:
                    try:
                        faults, hours_now = dtcmod.fetch_faults(client)
                    except policy.FAULT_POLL_NONFATAL as exc:
                        faults_error = str(exc)  # non-fatal: params still print
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
                    if dtc_on:
                        if faults_error is not None:
                            doc["faults_error"] = faults_error
                        else:
                            doc["faults"] = [
                                {
                                    "code": f.code,
                                    "description": f.description,
                                    "system": f.system,
                                    "present": f.present,
                                    "frequency": f.frequency,
                                    "age_h": dtcmod.age_hours(f, hours_now),
                                    "verified": f.verified,
                                }
                                for f in faults
                            ]
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
                    if dtc_on:
                        if faults_error is not None:
                            err_console.print(
                                f"[yellow]faults: read failed ({faults_error})[/yellow]"
                            )
                        elif not faults:
                            console.print("[green]No stored faults[/green]")
                        else:
                            console.print(live.faults_table(faults, hours_now))
            else:
                live.run_dashboard(
                    client,
                    profile,
                    console,
                    rate=rate,
                    stats=stats,
                    names=names,
                    dtc_interval=dtc_interval if dtc_on else 0.0,
                )
    finally:
        if stats is not None:
            err_console.print(stats.summary())


@app.command("panel")
@user_errors
def panel_cmd(
    ctx: typer.Context,
    rate: float = typer.Option(10.0, "--rate", help="Max poll rate (Hz)."),
    dtc_interval: float = typer.Option(10.0, "--dtc-interval", help="Seconds between fault polls."),
    frames: int | None = typer.Option(
        None, "--frames", hidden=True, help="Render N frames then exit (testing/CI)."
    ),
) -> None:
    """Everything-dashboard: ident header, all params, state bits, faults.

    Interactive keys: q quit, c clear DME fault memory (asks for an explicit
    y confirmation in the panel first — it is a write to the ECU).
    """
    cfg: Config = ctx.obj
    stats = live.TimingStats() if cfg.timing_debug else None
    try:
        with make_client(cfg) as client:
            profile, ident = resolve_profile(cfg, client)
            if ident is None:  # --profile override: still read the real ident
                try:
                    resp = client.query(ds2.ADDR["DME"], ms41.CMD_IDENT)
                    ident = ms41.parse_ident(resp.data)
                except (*policy.LINK, ds2.NakResponse, ms41.DecodeError):
                    ident = None  # header just omits it
            panelmod.run_panel(
                client,
                profile,
                ident,
                console,
                rate=rate,
                dtc_interval=dtc_interval,
                stats=stats,
                frames=frames,
            )
    finally:
        if stats is not None:
            err_console.print(stats.summary())


@app.command("dashboard")
@user_errors
def dashboard_cmd(
    ctx: typer.Context,
    rate: float = typer.Option(10.0, "--rate", help="Max poll rate (Hz)."),
    all_params: bool = typer.Option(
        False, "--all", help="Every profile param (default: core set)."
    ),
    params: str | None = typer.Option(None, "--params", help="Comma-separated param names."),
    dtc_on: bool = typer.Option(
        True, "--dtc/--no-dtc", help="Also show stored faults (polled between live reads)."
    ),
    dtc_interval: float = typer.Option(10.0, "--dtc-interval", help="Seconds between fault polls."),
    history: int = typer.Option(
        dashmod.DEFAULT_HISTORY, "--history", min=1, help="History ring-buffer size (samples)."
    ),
    frames: int | None = typer.Option(
        None, "--frames", hidden=True, help="Render N frames then exit (testing/CI)."
    ),
) -> None:
    """Full-screen tile dashboard: live squares with history sparklines.

    One tile per parameter — current value, window min/max, and a sparkline
    of recent samples. Interactive keys: q quit, c clear DME fault memory
    (asks for an explicit y confirmation — it is a write to the ECU),
    p pause rendering, +/- grow/shrink the visible history window.
    """
    cfg: Config = ctx.obj
    stats = live.TimingStats() if cfg.timing_debug else None
    try:
        with make_client(cfg) as client:
            profile, _ = resolve_profile(cfg, client)
            names = live.select_names(profile, all_params, params)
            dashmod.run_dashboard_screen(
                client,
                profile,
                console,
                port="sim" if cfg.sim else cfg.port,
                rate=rate,
                dtc_interval=dtc_interval if dtc_on else 0.0,
                names=names,
                history=history,
                stats=stats,
                frames=frames,
            )
    finally:
        if stats is not None:
            err_console.print(stats.summary())


SIA_EPILOG = (
    "Why no software reset? The E36 cluster does implement SIA_RESET at the "
    "diagnostic-job level, but the raw DS2 request bytes are not public, the "
    "adjacent command space includes GWSZ_RESET (odometer reset!), and Euro "
    "E36 clusters typically need an ADS interface a KKL cable cannot emulate. "
    "Sources and the full go/no-go: research/cluster-and-service-reset.md."
)


@app.command("sia", epilog=SIA_EPILOG)
def sia_cmd(
    kind: str = typer.Argument("oil", help="Which indicator to reset: 'oil' or 'inspection'."),
    timer: bool = typer.Option(
        False, "--timer", help="Run an on-screen countdown instead of flash counting."
    ),
) -> None:
    """Guided service-interval (SIA) reset — the pin-7 grounding procedure.

    This walkthrough sends NO wire traffic and needs no cable: the E36 service
    lights are reset electrically at the round 20-pin connector. Count the LED
    FLASHES (7 = oil service, 23 = inspection) rather than trusting a clock.
    """
    kind = kind.lower()
    if kind not in ("oil", "inspection"):
        raise fail("kind must be 'oil' or 'inspection'")
    flashes = 7 if kind == "oil" else 23
    seconds = 4.0 if kind == "oil" else 11.0

    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]Use ONLY pin 7 and pin 19.[/bold]\n"
            "Pin 7 = SIA reset input · pin 19 = ground.\n"
            "Pin 14 and pin 16 carry +12 V — shorting them to ground can blow "
            "fuses or damage the cluster. Do not guess pins: the numbers are "
            "molded into the connector body.\n"
            "A ~470 Ω resistor inline with the jumper wire is a sensible "
            "precaution (bare wire is what most guides use).",
            title="⚠ READ FIRST",
            border_style="red",
        )
    )
    steps = [
        "Ignition OFF. Find the round 20-pin diagnostic connector in the "
        "engine bay (near the strut tower / brake-fluid reservoir) and "
        "unscrew its cap.",
        "Turn the ignition to position II (dash lights on, engine NOT "
        "running). The service-interval LEDs light up.",
        f"Connect the jumper: into pin 7 first, then to pin 19 (ground). "
        f"Hold it there and COUNT THE LED FLASHES: release after "
        f"{flashes} flashes ({kind} reset, roughly {seconds:.0f} s).",
        "Remove the jumper (the reset commits when you pull it), switch the "
        "ignition off, then on again: the display should show 5 green bars "
        "and the warning cleared.",
    ]
    for i, step in enumerate(steps, 1):
        console.print(f"\n[bold cyan]Step {i}/4[/bold cyan]  {step}")
        if i == 3 and timer:
            _sia_countdown(seconds)
        if i < len(steps) and not typer.confirm("Done?", default=True):
            console.print("Stopped. Nothing was changed (this procedure is passive).")
            raise typer.Exit(code=1)
    console.print(f"\n[green]Done — {kind} service indicator should be reset.[/green]")
    console.print(
        "[dim]If the light is still on, repeat step 3 and rely on the flash "
        "count, not the clock — the timing windows differ between sources.[/dim]"
    )


def _sia_countdown(seconds: float) -> None:
    """Visible countdown as a backup pacing aid for --timer mode."""
    from rich.progress import BarColumn, Progress, TextColumn

    typer.confirm("Jumper connected — start the countdown?", default=True, abort=True)
    with Progress(
        TextColumn("holding…"),
        BarColumn(),
        TextColumn("{task.fields[left]:.1f}s"),
        console=console,
    ) as progress:
        task = progress.add_task("hold", total=seconds, left=seconds)
        t0 = time.monotonic()
        while (elapsed := time.monotonic() - t0) < seconds:
            progress.update(task, completed=elapsed, left=seconds - elapsed)
            time.sleep(0.1)
        progress.update(task, completed=seconds, left=0.0)
    console.print("[bold green]Remove the jumper NOW.[/bold green]")


LOG_EPILOG = (
    "Resilience (FTDI drops, car/research/session3-coldstart.md §2): by default the "
    "port is closed and reopened every --burst samples (40), which kept the "
    "KKL cable alive where continuous streaming killed it. On a link error the "
    "logger warns on stderr, closes the port, waits for the device node to come "
    "back (the --port path, or the only /dev/ttyUSB* if it re-enumerated under a "
    "new number), re-applies the 1 ms FTDI latency timer, reopens and resumes — "
    "appending to the same file. The outage is marked by a gap row: in CSV a row "
    "with t and every param column empty; in JSONL an "
    '{"event": "reconnect", "t", "gap_s", "port", "error"} line. t stays '
    "monotonic (seconds since the first sample). Rows are flushed as written "
    "(tail -f works). --no-reconnect restores fail-fast (always so under --sim)."
)


@app.command("log", epilog=LOG_EPILOG)
@user_errors
def log_cmd(
    ctx: typer.Context,
    out: Path = typer.Argument(..., help="Output file (.csv or .jsonl)."),
    rate: float = typer.Option(10.0, "--rate", help="Max sample rate (Hz)."),
    samples: int = typer.Option(
        0, "--samples", help="Stop after N real samples (0 = until Ctrl-C); gap rows don't count."
    ),
    all_params: bool = typer.Option(
        False, "--all", help="Every profile param (default: core set)."
    ),
    params: str | None = typer.Option(None, "--params", help="Comma-separated param names."),
    burst: int = typer.Option(
        datalog.DEFAULT_BURST,
        "--burst",
        help="Close and reopen the port every N samples (prophylactic vs FTDI drops; 0 = never).",
    ),
    reconnect: bool = typer.Option(
        True,
        "--reconnect/--no-reconnect",
        help="On a link error wait for the device and resume (default) or exit non-zero.",
    ),
) -> None:
    """Stream samples to CSV/JSONL until Ctrl-C (or --samples).

    Unverified params are marked: CSV column headers get a '?' suffix; JSONL
    rows carry a per-param "verified" field (SPEC invariant 3).
    """
    cfg: Config = ctx.obj
    if burst < 0:
        raise fail("--burst must be >= 0")
    stats = live.TimingStats() if cfg.timing_debug else None
    as_csv = out.suffix.lower() == ".csv"
    # ONE capture session for the whole run, however many times we reopen.
    capture = CaptureWriter("sim" if cfg.sim else cfg.port, cfg.capture_dir)
    shared = KeepOpenCapture(capture)
    logger: datalog.DataLogger | None = None
    try:
        try:
            transport = make_transport(cfg, capture=shared)
        except TransportError as exc:
            raise fail(str(exc)) from None
        if cfg.sim:
            # The sim has no device node to lose: "reopening" reuses the same
            # simulated DME / replay state, so sim output is unchanged.
            def opener(port: str) -> Transport:
                return transport
        else:

            def opener(port: str) -> Transport:
                return make_transport(replace(cfg, port=port), capture=shared)

        try:
            profile, _ = resolve_profile(cfg, ds2.DS2Client(transport))
            selected = live.select_names(profile, all_params, params)
            reads = live.plan(profile, names=selected)
        except BaseException:
            close_quietly(transport)
            raise
        specs = [p for p in profile.params if selected is None or p.name in selected]
        try:
            fh = out.open("w", newline="", encoding="utf-8")
        except OSError as exc:
            close_quietly(transport)
            raise fail(f"cannot write {out}: {exc}") from None
        with fh:
            logger = datalog.DataLogger(
                opener,
                transport,
                cfg.port,
                profile,
                reads,
                datalog.SampleWriter(fh, specs, as_csv),
                samples=samples,
                rate=rate,
                burst=burst,
                # The sim has no device to lose: a sim link error (a replay
                # missing a frame) is deterministic, so it stays fatal exactly
                # as before instead of waiting forever for --port to appear.
                reconnect=reconnect and not cfg.sim,
                stats=stats,
                latency_check=None if cfg.sim else datalog.latency_problem,
                warn=lambda msg: typer.echo(msg, err=True),
            )
            try:
                logger.run()
            finally:
                logger.close()
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()
        if stats is not None:
            err_console.print(stats.summary())
    written = logger.written if logger is not None else 0
    console.print(f"Wrote {written} sample(s) to {out}")
    if logger is not None and logger.reconnects:
        console.print(f"Survived {logger.reconnects} link drop(s) (gap rows mark each one)")


def _raw_request(data: bytes) -> tuple[int, bytes]:
    """Bytes typed at `e36 raw` -> (addr, payload).

    A complete frame when its length byte matches the byte count — and then
    its checksum must match too: a typo is refused, never reinterpreted as a
    different command. Otherwise `ADDR PAYLOAD...`, framed for you.
    """
    if len(data) >= 3 and data[1] == len(data):
        expected = ds2.xor_checksum(data[:-1])
        if data[-1] != expected:
            raise fail(
                f"checksum mismatch: frame ends {data[-1]:02X}, expected {expected:02X} "
                "(or leave the checksum off and it is computed for you)"
            )
        return data[0], bytes(data[2:-1])
    return data[0], bytes(data[1:])


@app.command()
@user_errors
def raw(
    ctx: typer.Context,
    hexbytes: list[str] = typer.Argument(..., help="Frame or addr+payload, hex bytes."),
    yes: bool = typer.Option(False, "--yes", help="Send a DME write without asking."),
) -> None:
    """Send an arbitrary DS2 frame; print the hex response (the probe tool).

    Accepts either a complete frame (len+checksum validated) or bare
    `ADDR PAYLOAD...` — the frame is then built for you. Idents and known DME
    reads go out freely; anything else to the DME is a write (confirmation,
    sent once, never retried); non-DME modules are ident-only.
    """
    cfg: Config = ctx.obj
    data = ds2.parse_hex(" ".join(hexbytes))
    if len(data) < 1:
        raise fail("need at least an address byte")
    addr, payload = _raw_request(data)
    kind = writes.classify_raw(addr, payload)
    if kind is writes.RawKind.REFUSED:
        raise fail(
            f"refusing {ds2.hexstr(payload) or '(empty)'} to 0x{addr:02X}: non-DME modules "
            "are ident-only (SPEC invariant 2)"
        )
    timing = ds2.SLOW
    if kind is writes.RawKind.DME_WRITE:
        question = (
            f"{ds2.hexstr(payload) or '(empty payload)'} is not a known DME read and may "
            "change ECU state. Send it once?"
        )
        if not yes and not typer.confirm(question):
            console.print("Aborted.")
            raise typer.Exit(code=1)
        timing = writes.WRITE_TIMING
    console.print(f"TX  {ds2.hexstr(ds2.build_frame(addr, payload))}")
    try:
        with make_client(cfg) as client:
            resp = client.query(addr, payload, timing=timing)
    except ds2.NakResponse as exc:
        console.print(f"RX  status 0x{exc.status:02X} ({exc.meaning})")
        raise typer.Exit(code=1) from None
    console.print(f"RX  {ds2.hexstr(resp.frame.raw)}")
    console.print(f"    status 0x{resp.status:02X}, data: {ds2.hexstr(resp.data) or '(none)'}")


@app.command()
def captures(
    ctx: typer.Context,
    show: int | None = typer.Option(None, "--show", help="Print events of session #N."),
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
