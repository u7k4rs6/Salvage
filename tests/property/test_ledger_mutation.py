"""Property test required by docs/03_SECURITY_AND_ACCESS.md section 8:

  "A property test mutates a random byte of a random entry and asserts verification fails."

Mutating any single byte of any entry must break verification. The strategy below builds an
arbitrary ledger, picks an entry, picks a field, picks a byte position inside that field, and
flips it. The one case that is not a defect is a mutation that produces an identical value, which
cannot happen here because the flip is guaranteed to change the byte.
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from salvage.ledger import LedgerEntry, entry_hash, verify_entries

MUTABLE_FIELDS = ("ts", "kind", "ref_type", "ref_id", "payload_json", "prev_hash", "hash", "seq")

_payloads = st.dictionaries(
    st.text(min_size=1, max_size=8),
    st.one_of(st.integers(-1000, 1000), st.text(max_size=12), st.booleans(), st.none()),
    max_size=4,
)

_entry_inputs = st.tuples(
    st.integers(0, 2_000_000_000),
    st.text(min_size=1, max_size=12).filter(lambda s: s.strip() != ""),
    st.text(min_size=1, max_size=12).filter(lambda s: s.strip() != ""),
    st.text(min_size=1, max_size=12).filter(lambda s: s.strip() != ""),
    _payloads,
)


def build_chain(specs: list[tuple]) -> list[LedgerEntry]:
    """Build a valid chain in memory, the same way salvage.ledger.Ledger.append does."""
    from salvage.ledger import GENESIS_HASH, canonical_json

    entries: list[LedgerEntry] = []
    prev_hash = GENESIS_HASH
    for index, (ts, kind, ref_type, ref_id, payload) in enumerate(specs, start=1):
        payload_json = canonical_json(payload)
        digest = entry_hash(index, ts, kind, ref_type, ref_id, payload_json, prev_hash)
        entries.append(
            LedgerEntry(index, ts, kind, ref_type, ref_id, payload_json, prev_hash, digest)
        )
        prev_hash = digest
    return entries


def mutate_one_byte(entry: LedgerEntry, field: str, position: int) -> LedgerEntry | None:
    """Flip one byte of one field. Returns None if the flip happened to be a no-op.

    The flip is done on the UTF-8 bytes, which is what "any single byte" means, then decoded with
    errors="replace" so the result is always a legal string. A flip that lands inside a multi-byte
    character therefore becomes U+FFFD, which is still a change.
    """
    data = entry.to_dict()
    original = str(data[field])
    raw = bytearray(original.encode("utf-8"))
    index = position % len(raw)
    raw[index] ^= 0x01
    mutated = bytes(raw).decode("utf-8", errors="replace")
    if field in ("seq", "ts"):
        digits = "".join(ch for ch in mutated if ch.isdigit()) or "0"
        value = int(digits)
        if value == int(data[field]):
            return None
        data[field] = value
    else:
        if mutated == original:
            return None
        data[field] = mutated
    return LedgerEntry.from_dict(data)


@given(
    specs=st.lists(_entry_inputs, min_size=1, max_size=6),
    entry_index=st.integers(0, 100),
    field=st.sampled_from(MUTABLE_FIELDS),
    position=st.integers(0, 1000),
)
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_any_single_byte_mutation_fails_verification(specs, entry_index, field, position):
    entries = build_chain(specs)
    assert verify_entries(entries).ok, "the unmutated chain must verify"

    target = entry_index % len(entries)
    replacement = mutate_one_byte(entries[target], field, position)
    assume(replacement is not None)
    mutated = list(entries)
    mutated[target] = replacement
    assert mutated[target].to_dict() != entries[target].to_dict(), "mutation must change something"

    result = verify_entries(mutated)
    assert not result.ok, f"mutating {field} of entry {target + 1} did not break verification"
    assert result.broken_seq is not None


@given(specs=st.lists(_entry_inputs, min_size=2, max_size=6), swap_at=st.integers(0, 100))
@settings(max_examples=100, deadline=None)
def test_reordering_two_entries_fails_verification(specs, swap_at):
    entries = build_chain(specs)
    i = swap_at % (len(entries) - 1)
    reordered = list(entries)
    reordered[i], reordered[i + 1] = reordered[i + 1], reordered[i]
    assert not verify_entries(reordered).ok
