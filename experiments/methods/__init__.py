"""Concrete method configurations for the main table + causal ablations.

Each method is a thin wrapper over (Verifier, Policy, PolicyContext, loop params).
Keep this file small: the method's identity is its PolicyContext + loop config.
"""
from experiments.methods.b0_zero_shot import make_b0_runner
from experiments.methods.b1_stderr_loop import make_b1_runner
from experiments.methods.b2_static_sft import make_b2_runner
from experiments.methods.b3_sft_stderr_loop import make_b3_runner
from experiments.methods.dvcr import make_dvcr_runner
from experiments.methods.dvcr_ablations import (
    make_dvcr_no_id_runner,
    make_dvcr_no_loop_runner,
    make_dvcr_no_structure_runner,
    make_dvcr_strict_zero_shot_runner,
)

__all__ = [
    "make_b0_runner",
    "make_b1_runner",
    "make_b2_runner",
    "make_b3_runner",
    "make_dvcr_runner",
    "make_dvcr_no_id_runner",
    "make_dvcr_no_loop_runner",
    "make_dvcr_no_structure_runner",
    "make_dvcr_strict_zero_shot_runner",
]
