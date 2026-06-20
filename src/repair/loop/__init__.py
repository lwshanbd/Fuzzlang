"""Inference-time loop: parallel sampling + verifier selection + terminal criterion."""
from repair.loop.search import run_repair_loop
from repair.loop.terminal import TerminalReason, is_trivial_deletion

__all__ = ["run_repair_loop", "TerminalReason", "is_trivial_deletion"]
