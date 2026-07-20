import json
from types import SimpleNamespace

from repair.run_quality_audit import audit_instances, summarize_audit


def test_summarize_audit_uses_eligible_compiler_fixes() -> None:
    rows = [
        {
            "ground_truth_ok": True,
            "compile_ok": True,
            "exact_match": False,
            "quality": {"degenerate": False},
        },
        {
            "ground_truth_ok": True,
            "compile_ok": True,
            "exact_match": True,
            "quality": {"degenerate": True},
        },
        {
            "ground_truth_ok": True,
            "compile_ok": False,
            "exact_match": False,
            "quality": {"degenerate": True},
        },
        {
            "ground_truth_ok": False,
            "compile_ok": False,
            "exact_match": False,
            "quality": {"degenerate": False},
        },
    ]

    summary = summarize_audit(rows)

    assert summary["n"] == 4
    assert summary["eligible"] == 3
    assert summary["eligible_compile_ok"] == 2
    assert summary["eligible_nonexact_compile_ok"] == 1
    assert summary["degenerate_compile_ok"] == 1
    assert summary["stale_ground_truth"] == 1


def test_audit_can_reverify_archived_outputs_with_current_compilers() -> None:
    erroneous = "before\nint value = missing;\nafter\n"
    corrected = "before\nint value = 0;\nafter\n"
    record = {
        "record_id": "r1",
        "erroneous_src": erroneous,
        "corrected_src": corrected,
        "diagnostics": [
            {
                "diag_name": "err_undeclared_var_use",
                "diag_msg": "missing",
                "file": "src/main.c",
                "line": 2,
                "col": 13,
            }
        ],
        "provenance": {
            "source": "project:src/main.c",
            "detail": {
                "source_path": "src/main.c",
                "compile_cmd": ["__CLANG__", "-fsyntax-only", "__SRC__"],
            },
        },
    }
    instance = {
        "record_id": "r1",
        "diag_name": "err_undeclared_var_use",
        "response": json.dumps({"corrected_window": "int value = 0;\n"}),
        "ground_truth_ok": False,
        "parse_ok": True,
        "compile_ok": False,
        "exact_match": True,
    }

    class FakeVerifier:
        def __init__(self) -> None:
            self.calls = []

        def verify(self, source, compile_cmd, *, logical_path):
            self.calls.append((source, compile_cmd, logical_path))
            return SimpleNamespace(ok=True, diag=None, raw_stderr="")

    verifier = FakeVerifier()
    audited = audit_instances(
        [record],
        [instance],
        target_format="window-rewrite",
        context_lines=0,
        verifier=verifier,
    )

    assert len(verifier.calls) == 2
    assert audited[0]["archived_ground_truth_ok"] is False
    assert audited[0]["archived_compile_ok"] is False
    assert audited[0]["ground_truth_ok"] is True
    assert audited[0]["compile_ok"] is True
