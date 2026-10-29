"""MS41 data layer: profiles, ident parsing, read planning, decode."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from e36cli import ms41
from e36cli.ms41 import (
    MAX_READ_CHUNK,
    Ident,
    build_read_payload,
    decode_reads,
    load_profiles,
    match_profile,
    parse_ident,
    plan_reads,
)

# Worked ident example from research/ms41-data.md §2 (RomRaider capture)
IDENT_PAYLOAD = b"143780611013021229600001158526000962142564"


@pytest.fixture(scope="module")
def profiles():
    return load_profiles()


# --- profile loading / schema ---------------------------------------------


# Every shipped profile, and the ECU IDs it claims. Keeping the mapping here
# (rather than deriving it) makes an accidental match_hw change a test failure.
SHIPPED_PROFILES = {
    "ms41-generic": (),
    "ms41.0": ("1429861",),
    "ms41.0-1405854": ("1405854",),
    "ms41.0-1429373": ("1429373",),
    "ms41.0-1432401": ("1432401",),
    "ms41.0-1438137": ("1438137",),
    "ms41.0-1440176": ("1440176",),
    "ms41.1": ("1437806",),
    "ms41.1-1438068": ("1438068",),
    "ms41.2": ("1406464",),
    "ms41.3-shinde1": ("SHINDE1",),
}

# Scraped-from-a-document profiles: nothing in them has been seen on a car, and
# the description has to say so (profile-expansion pass, 2026-10-27).
SCRAPED_PROFILE_IDS = tuple(
    pid for pid in SHIPPED_PROFILES if pid not in ("ms41-generic", "ms41.0-1429373")
)


def test_all_profiles_load(profiles):
    assert set(profiles) == set(SHIPPED_PROFILES)


def test_every_profile_matched_by_its_ecu_ids(profiles):
    for pid, ecu_ids in SHIPPED_PROFILES.items():
        assert profiles[pid].match_hw == ecu_ids, pid
        for ecu_id in ecu_ids:
            assert match_profile(ecu_id, profiles).id == pid


def test_no_ecu_id_claimed_by_two_profiles(profiles):
    claimed: dict[str, str] = {}
    for profile in profiles.values():
        for ecu_id in profile.match_hw:
            assert ecu_id not in claimed, (
                f"{ecu_id} claimed by {claimed.get(ecu_id)} and {profile.id}"
            )
            claimed[ecu_id] = profile.id


def test_scraped_profiles_announce_unverified(profiles):
    for pid in SCRAPED_PROFILE_IDS:
        profile = profiles[pid]
        assert profile.description.endswith("(unverified)"), pid
        assert not any(p.verified for p in profile.params), pid


def test_profile_schema(profiles):
    for profile in profiles.values():
        assert profile.id and profile.description
        assert profile.params, profile.id
        for p in profile.params:
            assert p.name and p.label
            assert 0 <= p.addr <= 0xFFFFFF
            assert p.size in (1, 2, 4)
            assert p.endian in ("big", "little")
            # verified params must cite the capture that proved them (garage
            # session 1, 2026-10-25, verified the 8 core physics params)
            if p.verified:
                assert p.verified_source, f"{profile.id}:{p.name} verified without source"
            assert p.source, f"{profile.id}:{p.name} missing provenance"
            assert callable(p._fn)  # formula compiled at load
            # formula actually evaluates across the raw range (load-time probe
            # only checks 0/1/max — walk the whole byte range for 1-byte params)
            for raw in (0, 1, (1 << (8 * p.size)) - 1):
                assert isinstance(p._fn(float(raw)), float)


def test_every_profile_has_a_core_subset(profiles):
    for profile in profiles.values():
        core = profile.core_params
        assert 6 <= len(core) <= 12, f"{profile.id}: {len(core)} core params"
        assert {"rpm", "coolant_temp"} <= {p.name for p in core}, profile.id


def test_profile_params_fit_the_read_planner(profiles):
    for profile in profiles.values():
        reqs = plan_reads(profile)
        assert reqs, profile.id
        covered = {p.name for r in reqs for p, _ in r.params}
        assert covered == {p.name for p in profile.params}, profile.id


def test_ms411_key_params(profiles):
    p = profiles["ms41.1"]
    assert p.param("rpm").addr == 0xDA2A
    assert p.param("coolant_temp").addr == 0xDA5A
    assert p.param("injector_pw").addr == 0xEF96  # MS41.1-specific column
    assert p.param("battery").addr == 0xFC9D
    # variant columns actually differ
    assert profiles["ms41.0"].param("injector_pw").addr == 0xECBC
    assert profiles["ms41.2"].param("injector_pw").addr == 0xEF7E


def test_generic_profile_has_no_variant_params(profiles):
    generic = profiles["ms41-generic"]
    names = {p.name for p in generic.params}
    assert "rpm" in names and "coolant_temp" in names
    for variant_only in ("injector_pw", "stft_b1", "ltft_b1", "load", "battery"):
        assert variant_only not in names


# --- ident parsing ----------------------------------------------------------


def test_parse_ident_worked_example():
    ident = parse_ident(IDENT_PAYLOAD)
    assert ident.ecu_id == "1437806"
    assert ident.hw_index == "11"
    assert ident.coding_index == "01"
    assert ident.diag_index == "30"
    assert ident.bus_index == "21"
    assert ident.mfg_week == "22"
    assert ident.mfg_year == "96"
    assert ident.supplier == "0000115852"
    assert ident.sw_index == "60"
    assert ident.change_index == "00"
    assert ident.serial == "962142564"
    assert ident.isn == "2564"
    assert ident.raw == IDENT_PAYLOAD


def test_parse_ident_tolerates_odd_length():
    ident = parse_ident(b"1429861XX")
    assert ident.ecu_id == "1429861"
    assert ident.serial is None and ident.isn is None
    assert ident.raw == b"1429861XX"


def test_parse_ident_non_ascii():
    ident = parse_ident(b"\xff" * 42)
    assert len(ident.ecu_id) == 7  # replaced chars, no crash


# --- profile matching -------------------------------------------------------


def test_match_by_ecu_id(profiles):
    assert match_profile(parse_ident(IDENT_PAYLOAD), profiles).id == "ms41.1"
    assert match_profile("1429861", profiles).id == "ms41.0"
    assert match_profile("1406464", profiles).id == "ms41.2"
    # SHINDE1 (MS41.3 custom firmware) has its own profile: MS41.2's map plus
    # the wideband channels that only exist in that firmware.
    assert match_profile("SHINDE1", profiles).id == "ms41.3-shinde1"
    assert profiles["ms41.3-shinde1"].param("wb_afr").addr == 0xE800


def test_match_falls_back_to_generic(profiles):
    assert match_profile("9999999", profiles).id == "ms41-generic"


def test_unsourced_ecu_ids_fall_back_to_generic(profiles):
    # SP-Daten lists these as MS41 HW-NRs, but no source publishes a RAM map for
    # them. They must NOT inherit a sibling's variant-specific addresses —
    # generic's common-only block is the honest answer (research/profile-scrape.md §4).
    for ecu_id in ("1427703", "7505858", "1437804"):
        assert match_profile(ecu_id, profiles).id == "ms41-generic"


# Scalings measured on the car to differ from the documented common block
# (car/research/session3-coldstart.md §4); addresses and sizes still must agree.
CAR_MEASURED_SCALINGS = {
    ("ms41.0-1429373", "knock_retard_global"),
    ("ms41.0-1429373", "o2_front_b1"),
    ("ms41.0-1429373", "o2_front_b2"),
}


def test_common_block_agrees_across_every_profile(profiles):
    # The §3.6.1 addresses are the same on every documented MS41 ECU ID; any
    # future profile that disagrees is a transcription error.
    baseline = {p.name: (p.addr, p.size, p.formula) for p in profiles["ms41-generic"].params}
    for profile in profiles.values():
        for p in profile.params:
            if p.name not in baseline or p.name == "tps":
                continue
            addr, size, formula = baseline[p.name]
            assert (p.addr, p.size) == (addr, size), f"{profile.id}:{p.name}"
            if (profile.id, p.name) not in CAR_MEASURED_SCALINGS:
                assert p.formula == formula, f"{profile.id}:{p.name}"


def test_variant_specific_addresses_differ_as_sourced(profiles):
    # The three documented MS41 columns really are three different maps.
    assert profiles["ms41.0"].param("injector_pw").addr == 0xECBC
    assert profiles["ms41.1"].param("injector_pw").addr == 0xEF96
    assert profiles["ms41.2"].param("injector_pw").addr == 0xEF7E
    # ds2.py's batch table scrape: 1432401/1438137 ride the MS41.0 column,
    # 1438068 the MS41.1 column — each listed under its own ECU ID.
    assert profiles["ms41.0-1432401"].param("battery").addr == 0xFB47
    assert profiles["ms41.0-1438137"].param("battery").addr == 0xFB47
    assert profiles["ms41.1-1438068"].param("battery").addr == 0xFC9D
    # the high-byte-only short-trim form the batch table documents
    assert profiles["ms41.0-1432401"].param("stft_b1_hi").addr == 0xED5C + 1
    assert profiles["ms41.1-1438068"].param("stft_b1_hi").addr == 0xF036 + 1


def test_common_only_profiles_omit_variant_params(profiles):
    # 1405854 / 1440176 appear only in the logger XML's shared ECU-ID lists, so
    # they get the common block and nothing that moves between variants.
    for pid in ("ms41.0-1405854", "ms41.0-1440176"):
        names = {p.name for p in profiles[pid].params}
        assert "rpm" in names and "coolant_temp" in names
        for variant_only in ("tps", "injector_pw", "stft_b1", "ltft_b1", "load", "battery"):
            assert variant_only not in names, f"{pid}:{variant_only}"


def test_unknown_ecu_id_falls_back_to_generic(profiles):
    # match_sw substring matching was removed (review #12: the SW part numbers
    # never occur in the ident payload) — unknown ECU IDs go generic.
    ident = Ident(raw=b"XXXXXXX...1438068DA...", ecu_id="XXXXXXX")
    assert match_profile(ident, profiles).id == "ms41-generic"


# --- read planning ----------------------------------------------------------


def test_plan_reads_batches_contiguous(profiles):
    profile = profiles["ms41.1"]
    reqs = plan_reads(profile)
    covered = {p.name for req in reqs for p, _ in req.params}
    assert covered == {p.name for p in profile.params}
    for req in reqs:
        assert 0 < req.count <= MAX_READ_CHUNK
        for p, off in req.params:
            assert req.addr + off == p.addr
            assert off + p.size <= req.count
    # the 0xDA2A..0xDA36 cluster (rpm/maf/idle valve, gaps <= 8) must share one request
    by_param = {p.name: req for req in reqs for p, _ in req.params}
    assert by_param["rpm"] is by_param["maf"] is by_param["idle_valve"]
    # far-apart params must not share (0xDA5A coolant vs 0xFC9D battery)
    assert by_param["coolant_temp"] is not by_param["battery"]


def test_plan_reads_subset_and_unknown(profiles):
    profile = profiles["ms41.1"]
    reqs = plan_reads(profile, names=["rpm", "coolant_temp"])
    assert {p.name for req in reqs for p, _ in req.params} == {"rpm", "coolant_temp"}
    with pytest.raises(KeyError):
        plan_reads(profile, names=["rpm", "nope"])


@given(
    addrs=st.lists(
        st.tuples(st.integers(0x8000, 0xFFF0), st.sampled_from([1, 2])),
        min_size=1,
        max_size=40,
        unique_by=lambda t: t[0],
    ),
    gap=st.integers(0, 32),
)
def test_plan_reads_property(addrs, gap):
    """Every param is covered exactly once, within bounds, regardless of layout."""
    params = tuple(
        ms41.ParamSpec(
            name=f"p{i}",
            label=f"p{i}",
            unit="",
            addr=a,
            size=s,
            formula="x",
            source="t",
        )
        for i, (a, s) in enumerate(addrs)
    )
    for p in params:
        object.__setattr__(p, "_fn", lambda x: x)
    profile = ms41.Profile(id="t", description="t", match_hw=(), params=params)
    reqs = plan_reads(profile, gap_tolerance=gap)
    seen: list[str] = []
    for req in reqs:
        assert 0 < req.count <= MAX_READ_CHUNK
        for p, off in req.params:
            assert req.addr + off == p.addr
            assert off >= 0 and off + p.size <= req.count
            seen.append(p.name)
    assert sorted(seen) == sorted(p.name for p in params)


# --- payload build / decode -------------------------------------------------


def test_build_read_payload_exact_bytes(profiles):
    # research/ds2-protocol.md §4.5: 2 bytes of MAF at 0xDA34 → 06 00 00 DA 34 02
    profile = profiles["ms41.1"]
    (req,) = plan_reads(profile, names=["maf"])
    assert build_read_payload(req) == bytes([0x06, 0x00, 0x00, 0xDA, 0x34, 0x02])


def test_decode_reads_known_values(profiles):
    profile = profiles["ms41.1"]
    # iat..coolant gap is 9 bytes; tolerance 16 merges them into one request
    (req,) = plan_reads(profile, names=["coolant_temp", "iat"], gap_tolerance=16)
    data = bytearray(req.count)
    data[profile.param("iat").addr - req.addr] = 100  # 100*0.747-48 = 26.7
    data[profile.param("coolant_temp").addr - req.addr] = 171  # 171*0.747-48 = 79.737
    values = decode_reads(profile, req, bytes(data))
    assert values["iat"].value == pytest.approx(26.7)
    assert values["coolant_temp"].value == pytest.approx(79.737)
    assert values["coolant_temp"].unit == "°C"
    assert values["coolant_temp"].verified is False


def test_decode_reads_little_endian_u16(profiles):
    profile = profiles["ms41.1"]
    (req,) = plan_reads(profile, names=["rpm"])
    # 800 rpm = 0x0320 little-endian on the wire
    values = decode_reads(profile, req, bytes([0x20, 0x03]))
    assert values["rpm"].value == 800
    assert values["rpm"].raw == 800


def test_decode_reads_mask(profiles):
    profile = profiles["ms41.1"]
    (req,) = plan_reads(profile, names=["maf_volts"])
    # 10-bit ADC: raw 0xFFFF masked to 0x3FF → full scale 5.0 V
    values = decode_reads(profile, req, b"\xff\xff")
    assert values["maf_volts"].value == pytest.approx(5.0)


def test_decode_reads_length_mismatch(profiles):
    profile = profiles["ms41.1"]
    (req,) = plan_reads(profile, names=["rpm"])
    with pytest.raises(ValueError):
        decode_reads(profile, req, b"\x00")


def test_trim_formula_midpoint(profiles):
    p = profiles["ms41.1"].param("stft_b1")
    assert p.decode((32768).to_bytes(2, "little")).value == pytest.approx(0.0)
    assert p.decode((65535).to_bytes(2, "little")).value == pytest.approx(50.0, abs=0.01)


# --- load-time profile validation (review finding #4) -------------------------


def _profile_toml(tmp_path, param_lines: str):
    text = (
        '[profile]\nid = "t"\ndescription = "t"\nmatch_hw = ["0000000"]\n\n'
        '[[param]]\nname = "p"\naddr = 0xDA2A\nsize = 1\n' + param_lines
    )
    (tmp_path / "t.toml").write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    "lines",
    [
        'formula = "x / 0"\n',  # ZeroDivisionError at poll time
        'endian = "middle"\n',  # bad endian
        'mask = "0x3FF"\n',  # mask as string
        'formula = "x * 10e400"\n',  # inf literal
        'formula = "x * 1' + "0" * 400 + '"\n',  # OverflowError literal
        "signed = true\nmask = 0x3FF\n",  # ambiguous combination
    ],
)
def test_bad_param_fields_raise_profile_error_at_load(tmp_path, lines):
    with pytest.raises(ms41.ProfileError):
        ms41.load_profiles(_profile_toml(tmp_path, lines))


def test_bad_addr_type_raises_profile_error(tmp_path):
    text = (
        '[profile]\nid = "t"\ndescription = "t"\n\n'
        '[[param]]\nname = "p"\naddr = "0xDA2A"\nsize = 1\n'
    )
    (tmp_path / "t.toml").write_text(text)
    with pytest.raises(ms41.ProfileError):
        ms41.load_profiles(tmp_path)


def test_decode_length_mismatch_is_typed(profiles):
    profile = profiles["ms41.1"]
    (req,) = plan_reads(profile, names=["rpm"])
    with pytest.raises(ms41.DecodeError):
        decode_reads(profile, req, b"\x00")


def test_shipped_profiles_have_core_subsets(profiles):
    for pid in ("ms41.0", "ms41.1", "ms41.2"):
        core = profiles[pid].core_params
        assert 8 <= len(core) <= 14, f"{pid} core set looks wrong: {len(core)}"
        assert {"rpm", "coolant_temp"} <= {p.name for p in core}
