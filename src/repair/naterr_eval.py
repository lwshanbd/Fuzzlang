"""Score repairs of errors developers actually made.

Every other FuzzLang evaluation asks whether a model can repair an error
FuzzLang injected. This asks whether it can repair one a developer committed,
recovered from LLVM history and reproduced by the pinned Clang.

**Why the success criterion is different here.** Elsewhere a repair succeeds
when the translation unit compiles clean. That works because the reference
repair also compiles clean, so a clean build is reachable. For a historical
error it usually is not: the file is from 2023 and the header tree is from
2026, so even the developer's own fix fails. Requiring a clean build would
score every instance zero and would be measuring the tree rather than the
model. Only 3 of 269 reproduced errors have a reference fix that still
compiles -- too few to say anything.

So the criterion is **did the error the model was shown go away**, which is
attributable to the model regardless of what else in the tree has drifted.
It is weaker than a clean build, and the reports must say so. Two things keep
it honest:

* deleting the offending code also eliminates the diagnostic, so every
  elimination is checked for degeneracy and the headline rate excludes those;
* the same criterion scores the base and the fine-tuned model, so the
  comparison between them does not depend on the criterion's strength.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence


def diagnostic_present(stderr: str, diag_id: int) -> bool:
    """True when the compiler reported this exact diagnostic ID.

    Matched on a word boundary so ``DiagID: 424`` is not found inside
    ``DiagID: 4242``.
    """
    if not stderr:
        return False
    return re.search(rf"DiagID:\s*{int(diag_id)}\b", stderr) is not None


def score_repair(result: Any, *, target_diag_id: int) -> dict[str, bool]:
    """Did this compile outcome get rid of the diagnostic the model was shown?"""
    if getattr(result, "ok", False):
        return {"compiles_clean": True, "target_eliminated": True}
    stderr = getattr(result, "raw_stderr", "") or ""
    return {
        "compiles_clean": False,
        "target_eliminated": not diagnostic_present(stderr, target_diag_id),
    }


def is_real_developer_error(
    corrected_result: Any, *, target_diag_id: int
) -> bool:
    """Did the developer's own commit address this diagnostic?

    Compiling a file from 2023 against a tree from 2026 invents errors nobody
    made -- a header deleted since, a member that has moved. Those reproduce
    exactly like a real error and are indistinguishable from the erroneous side
    alone. The discriminator is the fix: if applying the developer's own commit
    leaves the same diagnostic firing, they were not fixing it, and scoring a
    model on it would be scoring our reconstruction rather than a real repair.
    """
    return score_repair(corrected_result, target_diag_id=target_diag_id)[
        "target_eliminated"
    ]


def usable_retarget(
    *,
    removed_diag_lines: Mapping[int, int],
    window_first_line: int,
    window_last_line: int,
) -> int | None:
    """Pick a masked real error the model could actually repair, if any.

    ``removed_diag_lines`` maps a diagnostic ID the developer's fix removed to
    the line it was reported on. Only one inside the source window is usable:
    outside it the model is being asked to repair code it was never shown.
    Ties go to the diagnostic nearest the middle of the window, which is where
    the developer's own edit sits.
    """
    inside = {
        diag_id: line for diag_id, line in removed_diag_lines.items()
        if window_first_line <= line <= window_last_line
    }
    if not inside:
        return None
    middle = (window_first_line + window_last_line) / 2
    return min(inside, key=lambda d: (abs(inside[d] - middle), d))


def summarize_naterr(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts and rates over scored NatErr instances."""
    if not rows:
        raise ValueError("cannot summarize zero NatErr results")
    n = len(rows)
    eliminated = [r for r in rows if r.get("target_eliminated")]
    degenerate = [r for r in eliminated if r.get("degenerate")]
    clean = sum(1 for r in rows if r.get("compiles_clean"))
    return {
        "n": n,
        "parse_ok": sum(1 for r in rows if r.get("parse_ok")),
        "target_eliminated": len(eliminated),
        "target_eliminated_rate": round(len(eliminated) / n, 4),
        "degenerate": len(degenerate),
        "target_eliminated_nondegenerate": len(eliminated) - len(degenerate),
        "target_eliminated_nondegenerate_rate": round(
            (len(eliminated) - len(degenerate)) / n, 4
        ),
        "compiles_clean": clean,
        "compiles_clean_rate": round(clean / n, 4),
        "criterion": (
            "target_eliminated: the diagnostic the model was shown is absent "
            "from the repaired translation unit. Weaker than a clean build, "
            "which is unreachable for most historical errors because the "
            "surrounding tree has moved on; applied identically to every model."
        ),
    }
