from __future__ import annotations

import json
import sys

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.fuzzlang_dsl.context_variants import extract_contextual_injectors
from gen.fuzzlang_dsl import run_expand_context_variants as variants_cli


def _record() -> Record:
    return Record(
        record_id="seed-1",
        erroneous_src="int f() { return &value; }\n",
        corrected_src="int f() { return value; }\n",
        diagnostics=(DiagInfo(
            diag_id=101,
            diag_name="err_typecheck_invalid_lvalue_addrof",
            diag_msg="target",
            file="lib/f.cc",
            line=1,
            col=1,
            start_byte=0,
            end_byte=1,
            span_snippet="value",
        ),),
        provenance=Provenance(origin=Origin.MUTATE, source="llvm:lib/f.cc"),
        split=Split.TRAIN,
    )


def test_expand_context_variants_omits_existing_canonical_injector(
    tmp_path, monkeypatch,
):
    record = _record()
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps(record.to_dict()) + "\n")
    canonical = extract_contextual_injectors(
        record, diag_id=101, context_tokens=(2,),
    )
    existing = tmp_path / "existing.jsonl"
    existing.write_text("".join(item.to_json() + "\n" for item in canonical))
    out = tmp_path / "variants.jsonl"
    manifest = tmp_path / "manifest.json"

    monkeypatch.setattr(sys, "argv", [
        "run_expand_context_variants.py",
        "--records", str(records),
        "--exclude-injectors", str(existing),
        "--out", str(out),
        "--manifest-out", str(manifest),
    ])

    assert variants_cli.main() == 0
    assert len(out.read_text().splitlines()) == 3
    assert json.loads(manifest.read_text())["counts"] == {
        "input_records": 1,
        "excluded_injectors": 1,
        "emitted_injectors": 3,
    }
