"""Concrete method configurations for the main table + causal ablations.

Each method is a thin wrapper over (Verifier, Policy, PolicyContext, loop params).
Keep this file small: the method's identity is its PolicyContext + loop config.
"""
from experiments.methods.dvcr import make_dvcr_runner

__all__ = ["make_dvcr_runner"]
