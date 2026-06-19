"""Inference-time loop: parallel sampling + verifier selection + terminal criterion."""
from repair.loop.search import run_dvcr
from repair.loop.terminal import TerminalReason, is_trivial_deletion

__all__ = ["run_dvcr", "TerminalReason", "is_trivial_deletion"]
