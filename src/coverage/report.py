"""Render a CoverageReport as a human-readable summary."""
from __future__ import annotations

from coverage.tracker import CoverageReport


def format_report(r: CoverageReport) -> str:
    lines = [
        f"Diagnostic coverage (target multiplicity = {r.multiplicity_target})",
        f"  covered:         {r.covered}/{r.total}  ({r.coverage_fraction:.1%})",
        f"  covered @target: {r.covered_at_target}/{r.total}  ({r.coverage_at_target_fraction:.1%})",
        "  by component:",
    ]
    for comp, (cov, tot) in sorted(r.by_component().items(), key=lambda kv: -kv[1][1]):
        frac = cov / tot if tot else 0.0
        lines.append(f"    {(comp or '(none)'):<16} {cov:>5}/{tot:<5} ({frac:.0%})")
    lines.append(f"  gaps (below target): {len(r.gap_list())}")
    return "\n".join(lines)
