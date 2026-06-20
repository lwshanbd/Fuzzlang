"""Guided generation: target uncovered diagnostics using the compiler's own evidence.

Given a diagnostic and an example that triggers it (mined from Clang's regression
tests), an LLM writes a fresh correct/broken pair in a different scenario; the
verifier confirms it; a Record(Origin.GUIDED) is emitted. This reaches the long
tail of (mostly Sema) diagnostics that mechanical mutation cannot. See
docs/FuzzLang-Proposal.md, Direction 2.
"""
