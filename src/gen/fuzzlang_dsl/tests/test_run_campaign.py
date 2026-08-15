from __future__ import annotations

import hashlib
import json

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo, VerifierResult
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl import run_campaign as cli
from gen.realcorpus.clean_source_pool import CleanSourceTU


def _diag(name: str, path: str) -> DiagInfo:
    return DiagInfo(
        diag_id=71,
        diag_name=name,
        diag_msg=name,
        file=path,
        line=1,
        col=1,
        start_byte=0,
        end_byte=1,
        span_snippet="x",
    )


def _injector() -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag="err_target",
        target_diag_id=71,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="bad_exact",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "bad_exact"),),
    )


def _source() -> Record:
    path = "llvm/lib/Core.cpp"
    return Record(
        record_id="parent",
        erroneous_src="int f() { return missing; }\n",
        corrected_src="int f() { return 0; }\n",
        diagnostics=(_diag("err_parent", path),),
        provenance=Provenance(
            Origin.REAL,
            "llvm:llvm/lib/Core.cpp",
            {
                "project": "llvm",
                "source_path": path,
                "compile_cmd": ["__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"],
            },
        ),
        split=Split.TRAIN,
    )


class _Verifier:
    constructor_args = None

    def __init__(
        self,
        clang_bin: str,
        diagtool_bin: str,
        timeout_s: float,
        *,
        clang_c_bin: str,
    ):
        type(self).constructor_args = {
            "clang_bin": clang_bin,
            "clang_c_bin": clang_c_bin,
            "diagtool_bin": diagtool_bin,
            "timeout_s": timeout_s,
        }

    def verify(self, source: str, compile_cmd: list[str], *, logical_path: str):
        if "bad_exact" in source:
            return VerifierResult(False, _diag("err_target", logical_path), "exact")
        return VerifierResult(True, None, "")


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_select_injectors_shards_by_input_position_deterministically():
    injectors = [
        FuzzLangInjector(
            target_diag=f"err_target_{index}",
            language="c++",
            operation="replace",
            old_patterns=("<NUM>",),
            new_text="bad_exact",
            left_context=("return",),
            right_context=(";",),
            portable=True,
            replacement_parts=(("literal", "bad_exact"),),
        )
        for index in range(5)
    ]

    selected = cli._select_injectors(
        injectors, None, shard_count=2, shard_index=1,
    )

    assert [item.target_diag for item in selected] == ["err_target_1", "err_target_3"]


def test_cli_writes_canonical_outputs_manifest_checksums_and_uses_both_drivers(
    tmp_path, monkeypatch,
):
    injectors = tmp_path / "injectors.jsonl"
    sources = tmp_path / "sources.jsonl"
    records = tmp_path / "records.jsonl"
    rejections = tmp_path / "rejections.jsonl"
    manifest = tmp_path / "manifest.json"
    injectors.write_text(_injector().to_json() + "\n")
    sources.write_text(json.dumps(_source().to_dict(), sort_keys=True) + "\n")
    monkeypatch.setattr(cli, "FuzzlangClangVerifier", _Verifier)

    exit_code = cli.main([
        "--injectors", str(injectors),
        "--sources", str(sources),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--records-out", str(records),
        "--rejections-out", str(rejections),
        "--manifest-out", str(manifest),
        "--max-verifications", "4",
        "--max-verifications-per-injector", "2",
    ])

    assert exit_code == 0
    assert _Verifier.constructor_args == {
        "clang_bin": "/mock/clang++",
        "clang_c_bin": "/mock/clang",
        "diagtool_bin": "/mock/diagtool",
        "timeout_s": 10.0,
    }
    output_record = Record.from_dict(json.loads(records.read_text()))
    assert output_record.primary_diagnostic.diag_name == "err_target"
    payload = json.loads(manifest.read_text())
    assert payload["uses_llm_api"] is False
    assert payload["inputs"]["injectors"]["sha256"] == _sha256(injectors)
    assert payload["inputs"]["sources"]["sha256"] == _sha256(sources)
    assert payload["outputs"]["records"]["sha256"] == _sha256(records)
    assert payload["outputs"]["rejections"]["sha256"] == _sha256(rejections)
    assert payload["compiler"]["clang_c_bin"] == "/mock/clang"
    assert payload["compiler"]["clang_cxx_bin"] == "/mock/clang++"
    assert payload["injectors"][0]["target_rate"] == 1.0


def test_cli_accepts_clean_source_pool_as_a_non_dataset_input(tmp_path, monkeypatch):
    injectors = tmp_path / "injectors.jsonl"
    clean_sources = tmp_path / "clean-sources.jsonl"
    records = tmp_path / "records.jsonl"
    rejections = tmp_path / "rejections.jsonl"
    manifest = tmp_path / "manifest.json"
    corrected = "int f() { return 0; }\n"
    source = CleanSourceTU(
        source_id="llvm:llvm/lib/IR/Clean.cpp",
        project="llvm",
        source_path="llvm/lib/IR/Clean.cpp",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )
    injectors.write_text(_injector().to_json() + "\n")
    clean_sources.write_text(json.dumps(source.to_dict(), sort_keys=True) + "\n")
    monkeypatch.setattr(cli, "FuzzlangClangVerifier", _Verifier)

    assert cli.main([
        "--injectors", str(injectors),
        "--clean-sources", str(clean_sources),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--records-out", str(records),
        "--rejections-out", str(rejections),
        "--manifest-out", str(manifest),
    ]) == 0

    payload = json.loads(manifest.read_text())
    record = Record.from_dict(json.loads(records.read_text()))
    assert payload["inputs"]["clean_sources"]["sha256"] == _sha256(clean_sources)
    assert payload["source_policy"]["clean_source_tu_allowed"] is True
    assert record.provenance.detail["source_pool"] == "clean_source_tu"
    assert "parent_record_id" not in record.provenance.detail


def test_cli_excludes_bootstrap_witness_sources_from_clean_replay(tmp_path, monkeypatch):
    injectors = tmp_path / "injectors.jsonl"
    clean_sources = tmp_path / "clean-sources.jsonl"
    witnesses = tmp_path / "witnesses.jsonl"
    records = tmp_path / "records.jsonl"
    rejections = tmp_path / "rejections.jsonl"
    manifest = tmp_path / "manifest.json"
    corrected = "int f() { return 0; }\n"
    exemplar = CleanSourceTU(
        source_id="llvm:llvm/lib/IR/Exemplar.cpp",
        project="llvm",
        source_path="llvm/lib/IR/Exemplar.cpp",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )
    replay = CleanSourceTU(
        source_id="llvm:llvm/lib/IR/Replay.cpp",
        project="llvm",
        source_path="llvm/lib/IR/Replay.cpp",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )
    witness = _source()
    witness = Record(
        record_id=witness.record_id,
        erroneous_src=witness.erroneous_src,
        corrected_src=witness.corrected_src,
        diagnostics=witness.diagnostics,
        provenance=Provenance(
            witness.provenance.origin, exemplar.source_id, witness.provenance.detail,
        ),
        split=witness.split,
        language=witness.language,
    )
    injectors.write_text(_injector().to_json() + "\n")
    clean_sources.write_text(
        "".join(json.dumps(item.to_dict(), sort_keys=True) + "\n" for item in (exemplar, replay))
    )
    witnesses.write_text(json.dumps(witness.to_dict(), sort_keys=True) + "\n")
    monkeypatch.setattr(cli, "FuzzlangClangVerifier", _Verifier)

    assert cli.main([
        "--injectors", str(injectors),
        "--clean-sources", str(clean_sources),
        "--exclude-sources-from-records", str(witnesses),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--records-out", str(records),
        "--rejections-out", str(rejections),
        "--manifest-out", str(manifest),
    ]) == 0

    record = Record.from_dict(json.loads(records.read_text()))
    payload = json.loads(manifest.read_text())
    assert record.provenance.source == replay.source_id
    assert payload["source_policy"]["bootstrap_witness_sources_excluded"] is True
    assert payload["source_pool"]["excluded_bootstrap_witness_TUs"] == 1


def test_cli_can_limit_replay_to_requested_injector_ids(tmp_path, monkeypatch):
    injectors = tmp_path / "injectors.jsonl"
    sources = tmp_path / "sources.jsonl"
    records = tmp_path / "records.jsonl"
    rejections = tmp_path / "rejections.jsonl"
    manifest = tmp_path / "manifest.json"
    selected = _injector()
    unselected = FuzzLangInjector(
        target_diag="err_other_target",
        target_diag_id=72,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="bad_other",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "bad_other"),),
    )
    injectors.write_text(selected.to_json() + "\n" + unselected.to_json() + "\n")
    sources.write_text(json.dumps(_source().to_dict(), sort_keys=True) + "\n")
    monkeypatch.setattr(cli, "FuzzlangClangVerifier", _Verifier)

    assert cli.main([
        "--injectors", str(injectors),
        "--injector-id", selected.injector_id,
        "--sources", str(sources),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--records-out", str(records),
        "--rejections-out", str(rejections),
        "--manifest-out", str(manifest),
    ]) == 0

    payload = json.loads(manifest.read_text())
    assert payload["inputs"]["injectors"]["records"] == 2
    assert payload["injector_selection"] == {
        "requested_injector_ids": [selected.injector_id],
        "shard_count": 1,
        "shard_index": 0,
        "selected_input_rows": 1,
        "selected_injector_ids": [selected.injector_id],
    }
    assert [item["injector_id"] for item in payload["injectors"]] == [
        selected.injector_id,
    ]
