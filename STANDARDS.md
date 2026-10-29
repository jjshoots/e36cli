# Code standards

The bar for this repo, agreed by a four-lens review panel (architecture, robustness,
readability, tests/tooling) on 2026-10-30, then ratified with amendments. SPEC.md
stays the product contract; this file is how the code that implements it is built.
Each rule names how compliance is checked; prefer making a check a test or a CI gate.

| ID | Category | Standard |
|---|---|---|
| [STD-01](#std-01) | architecture | One-way layer DAG; the engine imports neither Rich nor Typer |
| [STD-02](#std-02) | invariants | Capture is structurally unavoidable, complete and terminal |
| [STD-03](#std-03) | error-handling | One exception taxonomy, one failure-policy classifier that mirrors SPEC, one CLI exit mapping |
| [STD-04](#std-04) | robustness | Wrap every foreign failure at the layer boundary, with no gaps |
| [STD-05](#std-05) | robustness | Single owner per resource; acquire inside the guard; cleanup never masks the primary error |
| [STD-06](#std-06) | concurrency | Poller thread: no silent death, cooperative stop, transport never closed under a live thread |
| [STD-07](#std-07) | protocol | Wire timing is frozen, validated, and derived from one byte-count cost model |
| [STD-08](#std-08) | invariants | Guarded writes: one service per write, never retried, honest outcome; raw is guarded and never guesses |
| [STD-09](#std-09) | data-integrity | Strict schemas for profiles and the DTC DB, with enforced provenance, validated at load |
| [STD-10](#std-10) | data-integrity | Decoders are total and never silently wrong |
| [STD-11](#std-11) | ux-robustness | User-facing failures: inputs validated before the wire, messages actionable, never a traceback |
| [STD-12](#std-12) | structure | Thin CLI commands; one implementation per idiom; bounded complexity |
| [STD-13](#std-13) | structure | One TUI session runner; views supply render and key handling only |
| [STD-14](#std-14) | types | Domain types: complete at construction, immutable, named fields, closed sets typed, explicit defaults |
| [STD-15](#std-15) | encapsulation | Privacy boundaries hold in src and tests |
| [STD-16](#std-16) | testability | Side effects injected once; test suite hermetic and deterministic |
| [STD-17](#std-17) | testing | SPEC invariants are pinned by tests that can fail |
| [STD-18](#std-18) | testing | Command-surface coverage is derived, not hand-maintained |
| [STD-19](#std-19) | data-provenance | Car-specific facts live under car/, are indexed, and goldens are exercised, honest and scrubbed |
| [STD-20](#std-20) | tooling | Static analysis gate: mypy --strict on src, typed seams, no file-scoped waivers |
| [STD-21](#std-21) | readability | Protocol knowledge is traceable: named constants and contract docstrings with citations |
| [STD-22](#std-22) | maintainability | No dead code or test-only public API in src |
| [STD-23](#std-23) | ci-release | Reproducible toolchain; release ships exactly what was tested |
| [STD-24](#std-24) | testing | Suite budget and golden-format contract |

## STD-01

**One-way layer DAG; the engine imports neither Rich nor Typer**

Imports may only point down this order: capture -> transport -> ds2 -> {formula, ms41} -> {dtc, sim} -> engine (poll_once, plan, TimingStats, Poller, LiveStore, DataLogger, doctor) -> views (live render, panel, dashboard) -> cli. A module may import from its own layer or from lower ones. sim is a Transport implementation: it may import capture, transport, ds2 and ms41, but nothing from the engine or views. Capture-side helpers such as KeepOpenCapture, or a non-closing CaptureSink wrapper, live in capture.py. rich, typer, termios, tty and sys.stdin may appear only in view modules and cli.py. The polling and logging engine must import cleanly when rich is not installed.

*Check:* Add a pytest that walks each module's AST imports and fails on any upward import, or on a rich/typer/termios import outside views and cli (an import-linter contract also works). `grep -n '^from rich' src/e36cli/{datalog,ds2,ms41,dtc,transport,capture,formula,sim}.py` must be empty.

## STD-02

**Capture is structurally unavoidable, complete and terminal**

(a) Every Transport that touches the wire, real or sim, is built by a single factory. That factory requires a CaptureSink, a Protocol defined in capture.py with record() and close(). Capture is applied in exactly one place: either a CapturingTransport decorator or a constructor argument that is not Optional. No code assigns another object's `_capture`. (b) Every byte that crosses the port is recorded, including bytes that flush_input throws away. Before reset_input_buffer, drain in_waiting and record those bytes as rx with a discarded marker. Port open, close and reopen are recorded as meta events. (c) A failure to write the capture raises a dedicated CaptureError. It is fatal everywhere and never counts as a link error. (d) A closed sink is terminal: record() after close() raises CaptureError and never opens a new session file.

*Check:* `grep -n '_capture =' src` matches only inside __init__. `SerialTransport(`/`SimTransport(` appear only in the factory. Tests: (1) a fake serial with pending bytes, then flush_input(), leaves those bytes in the capture; (2) a record() that raises OSError makes `e36 log` exit non-zero within one iteration; (3) record() after close() raises and the capture dir holds exactly one file; (4) three burst reopens give three open markers; (5) every CLI transport path writes a capture file.

## STD-03

**One exception taxonomy, one failure-policy classifier that mirrors SPEC, one CLI exit mapping**

All project errors derive from a root E36Error, with branches for link/transient errors (TransportError, Timeout, ChecksumError, EchoMismatch), deterministic protocol errors (NakResponse), data errors (ProfileError, DecodeError, DtcError, FormulaError, UnknownParamError) and CaptureError. Whether an error means retry/reconnect, fatal, or bug is defined once, as named policy tuples or a classify() function in one module, and the Poller, DataLogger, scan and cli all import it. If live and log are meant to differ (for example on NakResponse), the difference is two named policies side by side. The policies are the single source for SPEC's 'Failure policy' paragraphs: any conflict is resolved in the same change, either by editing SPEC or by changing the code. Library code never uses KeyError, ValueError or typer.Exit as a domain signal. cli.py maps exceptions to messages and exit codes in one decorator or context manager. `except Exception` is allowed only at a thread or process boundary, or for a documented termios.error escape, and needs a comment saying why.

*Check:* `grep -rn 'except KeyError' src/e36cli/cli.py` is empty. `grep -rn 'except (' src` shows only imported named policy tuples. A table-driven test runs every exception class through the classifier for Poller, DataLogger and scan, and is checked against a table copied from SPEC, including fault-poll errors that are not wire errors. Every `except Exception` hit has a comment.

## STD-04

**Wrap every foreign failure at the layer boundary, with no gaps**

Every call into pyserial, termios, tomllib or the filesystem is wrapped so it re-raises a project-typed error `from exc`. In SerialTransport this covers write, flush (tcdrain), the timeout setter, read, reset_input_buffer and close. Use `except Exception` wherever termios.error can escape. Loaders turn TOMLDecodeError, OSError and shape errors (KeyError, TypeError, AttributeError) into ProfileError or DtcError. CaptureReader counts any malformed line as malformed, including valid JSON that is not an object or has an unknown `dir`, and never crashes on it. It raises a typed error for an unsupported header version. Each wrapper has a test with a fake object that raises the foreign type.

*Check:* Every `self._ser.` call in transport.py sits inside a try that converts to TransportError. Tests: (1) a fake serial raising termios.error from flush() and from close(); (2) a malformed TOML profile and a DTC entry with no `text`, each giving a one-line CLI error with no 'Traceback'; (3) capture lines `5` and `[]` counted as malformed; (4) header version 99 rejected.

## STD-05

**Single owner per resource; acquire inside the guard; cleanup never masks the primary error**

Ports, capture files, output files, threads and TTY modes are each owned by exactly one function, using with, ExitStack or try/finally. A resource is acquired only after the guard that releases it is in place: poller.start(), tcgetattr and setcbreak all go inside the try whose finally undoes them. Hardware teardown goes through one shared quiet-close helper, which logs the close error and swallows it so it cannot replace the original exception. SerialTransport.close always closes its capture, even if the port close raises.

*Check:* Every `finally:`/`__exit__` that calls close() goes through the helper. Every `.start()` and `setcbreak` sits inside its try. Test: a transport whose recv and close both raise makes the command exit 1 with the recv message.

## STD-06

**Poller thread: no silent death, cooperative stop, transport never closed under a live thread**

(a) Poller.run wraps the whole loop iteration, including the try's else-branch store update, the clear and the fault poll, so any exception sets `fatal` before the thread exits. Render loops treat a thread that is no longer alive with fatal unset and no user stop as fatal too. (b) stop_event is checked between individual requests, not only between full polls. (c) The join bound is derived from ds2.Timing: deadline x (retries+1) plus busy delays, for the longest single request. It is a named constant with the derivation next to it. If join times out, the caller does not close the transport; it reports the problem and exits non-zero. (d) Cross-thread state goes only through LiveStore's locked methods. Any helper that hands a client to a thread documents the ownership transfer.

*Check:* `grep -n 'join(timeout=' src` uses the derived constant. Thread tests install a threading.excepthook (or run with filterwarnings=error for unhandled-thread-exception warnings) that fails on any unhandled thread death. Named tests: (1) a store whose update() raises ends with poller.fatal set and CLI exit 1; (2) a non-wire exception in request_clear gives exit 1; (3) with a delay injected into the fault poll and then q, close() is called only after `not poller.is_alive()`.

## STD-07

**Wire timing is frozen, validated, and derived from one byte-count cost model**

ds2.Timing is a frozen dataclass and validates itself in __post_init__: deadline > 0, retries >= 0, resync_budget >= 0, busy_delay >= 0. The presets SLOW and CLEAR cannot be mutated; variants are made with dataclasses.replace. A single function in src models wire cost: 9600 baud, 11 bits per byte, plus echo and gap. The DS2 layer uses it to derive each request's deadline from the expected response length, and --timing-debug and the perf tests use the same function. Perf tests are parametrized over the default sim profile and ms41.0-1429373, and are labelled as model ceilings. The only sleeps at or below the DS2 layer are the inter-frame gap and the busy backoff, both bounded and both in Timing. Runtime invariants never use `assert`.

*Check:* Test: for every ReadRequest that plan_reads can emit, the effective deadline exceeds the modelled wire time plus a margin. Mutating `ds2.SLOW.deadline` raises FrozenInstanceError. `Timing(retries=-1)` raises ValueError. `grep -n '9600' tests/` is empty. `grep -n 'assert ' src` is empty.

## STD-08

**Guarded writes: one service per write, never retried, honest outcome; raw is guarded and never guesses**

Each ECU state change has exactly one implementation in the protocol-services layer, for example dtc.clear_faults(client). It is the only code that sends CMD_DTC_CLEAR, and it holds the preconditions for future activations and resets. Writes are sent with retries=0. A timeout after TX is reported as 'outcome unknown', not 'failed', and is followed by a re-read to verify. The confirmation text for the CLI prompt and the TUI banner is one shared constant or component. `raw` refuses known write opcodes, and any non-ident frame to a non-DME address, unless the user passes --yes. When it does send such a frame, it uses retries=0. `raw` never guesses between a full frame and addr+payload: a bad checksum on input whose length byte matches is an error, not a reinterpretation.

*Check:* `grep -rn 'CMD_DTC_CLEAR' src` matches only the definition, the service and sim.py. Tests: (1) `e36 --sim raw 80 ...` without --yes exits non-zero and the capture has no tx; (2) `raw 12 04 00 17` exits non-zero with no tx; (3) a clear that times out reports 'unknown' and triggers a re-read; (4) a declined `dtc clear` leaves no 0x05 frame in the capture; (5) the banner string appears at exactly one site.

## STD-09

**Strict schemas for profiles and the DTC DB, with enforced provenance, validated at load**

The profile and DTC TOML loaders reject unknown keys at every level. Every param and DTC entry needs a non-empty string `source` and a bool `verified`. verified=true also requires verified_source and the ECU id(s) the value was observed on. A profile whose match_hw does not cover those ids (for example ms41-generic) must state the scope explicitly. match_hw must be list[str]. label, unit and formula must be strings. Param names and profile ids must be unique. Every violation raises ProfileError or DtcError naming the file and the entry. Each validation branch has a parametrized negative test, and the loader and validator have 100% branch coverage. The DTC DB is converted to typed dataclasses once at load, and its loader takes no unused parameters.

*Check:* `pytest --cov=e36cli.ms41 --cov=e36cli.dtc --cov-branch` shows full coverage of the validator and both loaders. There is a parametrized case for each `raise`. All shipped TOMLs load under strict mode. `grep -n 'get("source", "")' src` is empty.

## STD-10

**Decoders are total and never silently wrong**

For any bytes passed to parse_ident, decode_reads, ParamSpec.decode, decode_dtc_response or decode_hours_counter, the result is either a value or a DecodeError/DtcError that includes the offending bytes in hex. Runtime formula evaluation is wrapped so that ArithmeticError and non-finite results become DecodeError. The DTC record size comes from the command when the command fixes it (04 01 gives 10 bytes, 14 01 gives 11). Otherwise, decode only if exactly one known size fits the payload length, and raise DtcError with the payload in hex if more than one fits. All output writers keep the same lossless precision.

*Check:* Hypothesis tests feed arbitrary bytes into each decoder and accept only the project's typed errors. A count=2 DTC payload with 2 pad bytes decodes both codes correctly. CSV and JSONL rows for the same sample round-trip to equal floats.

## STD-11

**User-facing failures: inputs validated before the wire, messages actionable, never a traceback**

CLI numeric options are constrained in Typer: rate >= 0 (0 means unthrottled, as documented), dtc_interval >= 0, history >= 1, samples >= 0, burst >= 0. Hex input is length-checked inside the error handler, before build_frame. Every wire error that reaches the user names the operation, the module address, the command bytes, how many attempts were used out of how many allowed, and any partial bytes in hex. A lost link is never presented as an absent module: scan stops with a link error rather than reporting modules as 'silent'.

*Check:* A parametrized CliRunner test over bad values for each numeric option, plus a 300-byte `raw`, asserts exit != 0 and no 'Traceback'. A scan whose transport raises TransportError at the second address exits non-zero.

## STD-12

**Thin CLI commands; one implementation per idiom; bounded complexity**

A command body only validates options, opens a client through the factory, calls one named service in a lower layer, and renders through a view helper or a typed to_dict() serializer. Only `raw` and `scan` may build protocol bytes. Repeated options are declared once as Annotated aliases (Rate, Params, AllParams, DtcOn, DtcInterval). The ident read, fault-table rows, the --json document and the port label are each implemented once. The tool-enforced gate is ruff C90 (max-complexity 12) plus PLR0912/PLR0915. A function length of about 60 lines is a guideline for review.

*Check:* `grep -n 'client.query' src/e36cli/cli.py` matches only raw and scan. `ruff check --select C90,PLR0912,PLR0915 src` passes. Tests cover each JSON and snapshot serializer without CliRunner.

## STD-13

**One TUI session runner; views supply render and key handling only**

The lifecycle shared by live, panel and dashboard is written once, in a run_tui helper. It creates the store and Poller, enters cbreak, runs the Live loop at one named refresh rate, reads keys from an injected key reader, stops and joins under STD-06, restores the terminal, and raises LiveFatal. It accepts an optional frame limit for bounded runs. Each view provides a render(store, controller) function and a controller that does not touch the wire. Selecting params by name is one Profile.select(names) method.

*Check:* `grep -n 'poller.join\|tty.setcbreak\|LiveFatal(poller.fatal)' src` matches one site. `grep -n 'p.name in' src` matches only Profile.select. Panel and dashboard key handling is tested through an injected key reader.

## STD-14

**Domain types: complete at construction, immutable, named fields, closed sets typed, explicit defaults**

Value, config and parsed-record dataclasses are frozen, with slots where possible, and work as soon as they are constructed. No field that defaults to None is filled in later with object.__setattr__. Compiled artifacts are set by a named constructor (ParamSpec.from_toml) or kept in a separate compiled type. Anything with 3 or more related fields uses a NamedTuple or dataclass, never a positional tuple or a list used as a struct. Closed value sets (endian, capture direction, sim fault kind, controller state) are Literal or Enum aliases defined once and narrowed at the TOML/CLI boundary. Mutable state holders keep their fields private, expose locked methods, and return immutable snapshot dataclasses. Optional parameters default with `if x is None`, never `x or default`, unless the falsy case really means the same as absent, in which case a comment says so.

*Check:* `grep -n 'object.__setattr__' src` is empty. `grep -n 'list\[list\]' src` is empty. `grep -nE '= \w+ or ' src` hits only commented cases. Constructing each domain dataclass directly in a test gives a working object.

## STD-15

**Privacy boundaries hold in src and tests**

No module reads, writes or imports another module's `_`-prefixed names. Tests do not call private methods or mutate private state. When a collaborator or test needs a seam, it becomes public API, a constructor or factory parameter, or a test-support module. Fault injection in test doubles is keyed on protocol units (writes or requests), not on how many read() calls an implementation happens to make.

*Check:* Enable ruff SLF001 for src and tests, with only justified line-level noqa. `grep -rn 'import _' src` is empty. FlakySerial/FakePort fail_after counts write() calls.

## STD-16

**Side effects injected once; test suite hermetic and deterministic**

Transport factories, clocks, sleeps, device discovery, sysfs paths, key readers and env lookups are parameters or Config fields, following the existing DataLogger and Poller pattern. Env vars (E36CLI_CAPTURE_DIR, E36CLI_SIM_DTCS) are read once, in the Typer callback. tests/conftest.py has one autouse fixture that points E36CLI_CAPTURE_DIR and HOME at tmp, and no test module redeclares it. Tests control time through injected clocks and randomness through seeded rngs. Real-thread tests are marked and run under pytest-timeout. Hypothesis uses a CI profile (derandomize=True, with an explicit deadline).

*Check:* `grep -rn 'os.environ' src` matches only the callback. `grep -rn 'CAPTURE_DIR' tests/` matches only conftest.py. pytest-timeout is configured. CI runs the suite with HOME pointed at an empty read-only directory.

## STD-17

**SPEC invariants are pinned by tests that can fail**

tests/test_invariants.py has at least one named test per SPEC invariant. (1) Every TX frame of every command that touches the wire appears in the capture. (2) Declined or unguarded writes put zero write opcodes on the wire. (3) Every rendered unverified value carries '?', asserted on the specific row. (4) Covered by STD-18. (5) A transport double asserts a single owning thread and no send before the previous recv. Assertions must be able to fail: no tautological disjunctions, no no-op normalisations, and no single-character substring checks against a whole screen.

*Check:* Each invariant number maps to a named test. Mutation spot-check: deleting the typer.confirm in dtc_clear, or the record() call in SerialTransport.send, makes test_invariants.py fail.

## STD-18

**Command-surface coverage is derived, not hand-maintained**

A test enumerates the registered Typer commands and sub-apps and asserts that each one has at least one --sim CliRunner test that exits 0 and does real work, not just --help. Interactive TUIs are exercised through the STD-13 run_tui seams (an injected key reader that sends 'q', plus a frame limit). Where a CLI flag cannot be avoided (the existing dashboard --frames), it must be hidden=True and listed in the STD-22 vulture allowlist with a comment.

*Check:* test_command_surface compares the registered command names with the commands exercised under --sim. The set difference is empty.

## STD-19

**Car-specific facts live under car/, are indexed, and goldens are exercised, honest and scrubbed**

Facts about the owner's car live only under car/ (dossier, session log, captures, car-specific research) plus the ECU-type profile data/profiles/ms41.0-1429373.toml. src/ holds no car-specific constants. car/README.md is the index: it lists what lives where, including the runtime capture dir (~/.local/share/e36cli/captures/, $E36CLI_CAPTURE_DIR). Every capture in car/captures/ is loaded by at least one test. Golden tests assert wire truth (byte-exact frames) separately from decoded values that are written down independently. Every verified_source path resolves. Security-sensitive identifiers (the DME production serial, whose tail is taken to be the EWS ISN; any VIN) are replaced with a fixed placeholder, with the DS2 XOR checksum recomputed, before a capture is committed.

*Check:* tests/test_car_fixtures.py fails on any ident frame in car/captures/ whose serial field is not 000000000. A test resolves every verified_source path and checks that every car/captures/ file is referenced by a test. `grep -rn 1429373 src/` is empty.

## STD-20

**Static analysis gate: mypy --strict on src, typed seams, no file-scoped waivers**

CI runs `uv run mypy --strict src` from the locked dev group, never through uvx, with zero errors. types-pyserial is in the dev group, and `python_version = "3.11"` is set in [tool.mypy]. Every seam (Transport, SerialLike, CaptureSink, Clock, Opener, KeyReader) is a Protocol or a Callable alias. Every `# type: ignore` has an error code and a reason. Tests are excluded from strict mode until they are annotated. pyproject has no file-scoped ruff ignores or format excludes for src: suppressions are line-level noqa with a code and a reason. The ruleset adds S101, BLE, DTZ, SLF, PT, C90 and PLR0912/0915 to the existing E/F/W/I/UP/B/SIM/RUF. An import inside a function needs a one-line reason.

*Check:* ci.yml has a typecheck job. `grep -n -A5 'per-file-ignores' pyproject.toml` shows only tests entries. `ruff check src tests` passes with the expanded rule set.

## STD-21

**Protocol knowledge is traceable: named constants and contract docstrings with citations**

Every DS2 status byte, command byte, module address, flag bit and unit scale used in logic is a named constant in the module that owns it (ds2, ms41, dtc). It is defined once, with a research or fixture citation, and the sim uses the same constants. Range bounds are named limits (e.g. MAX_ADDR_24). Public classes and module functions in transport, ds2, ms41, dtc, capture and formula have docstrings. Methods get one only when they are longer than about 5 lines or carry a contract. A docstring must state units, what None means, or which errors are raised; otherwise it is left out. Factual claims about the wire or the data in comments cite research/ or a capture. Shared UI tuning values (default rate, refresh rate, default port) are defined once.

*Check:* `grep -rnE '0x[0-9A-Fa-f]{2}' src` hits only constant definitions, comments and docstrings. `ruff check --select D101,D103 src/e36cli/{transport,ds2,ms41,dtc,capture,formula}.py` passes, with D102 using ignore-decorators=["property"].

## STD-22

**No dead code or test-only public API in src**

Every public symbol in src is used by src, or is a documented extension point listed in TODO.md. Code that only tests use is either wired into a command or deleted along with its tests. Branches that cannot change the result are removed. vulture runs in CI at min-confidence 80, with an allowlist for Typer entry points and hidden test hooks such as --frames.

*Check:* `uvx vulture src --min-confidence 80` is clean apart from allowlisted items, and each allowlisted extension point has a TODO.md entry.

## STD-23

**Reproducible toolchain; release ships exactly what was tested**

ruff, mypy, pytest-timeout and coverage are locked dev dependencies. CI and pre-commit run them through `uv run`, or the pre-commit revs match uv.lock. CI uses `uv sync --locked`. pytest addopts include --strict-markers, -ra, filterwarnings=error and xfail_strict. The tag must equal the pyproject version and e36cli.__version__ (taken from importlib.metadata), and a test asserts this. The release gate runs the full Python matrix, including the newest version that requires-python allows, plus the wheel smoke test. The smoke test exercises the packaged DTC DB and --sim-fixture. Publish uploads the artifact that was tested, not a rebuild. Actions in privileged jobs are pinned by SHA.

*Check:* `grep -n 'uvx' .github/workflows/*.yml` is empty. A test asserts importlib.metadata.version('e36cli') == e36cli.__version__. release.yml needs the matrix and smoke jobs, has a tag/version equality step, and downloads the artifact before publishing.

## STD-24

**Suite budget and golden-format contract**

(a) CI runs `pytest --cov=e36cli --cov-branch --cov-fail-under=<floor>`, and the floor only moves up. (b) Every test runs under pytest-timeout, and `--durations` is reported, to keep SPEC's '< 10 s' target visible. A per-test timeout is preferred over a flaky gate on total wall time. (c) CaptureReader validates the header version against CAPTURE_VERSION and validates `dir` against Literal['tx','rx','meta']. (d) The session header records the e36cli version and the matched profile id, so goldens describe themselves.

*Check:* pytest config contains --cov-fail-under and timeout. A test with header version 99 expects a typed error. A new capture's header contains `e36cli_version`.
