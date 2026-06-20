"""diagnostic repair's parallel-sample + verifier-select loop.

Semantics (FINAL_PROPOSAL):
- Start with one branch: the original buggy source.
- Turn 0: policy produces K proposals from the single branch. Test each.
  If any compiles OK → SUCCESS (verifier picks first OK, shortest-edit tiebreak).
  Otherwise fork the single branch into up to K *children*, one per valid
  failed proposal. Each child's state = (new_src, new_diag, trajectory+=...).
- Turn 1..T-1: we have up to K live branches. Each branch independently
  produces K proposals (= K² proposals per turn, = K² verifier calls). If any
  OK, SUCCESS. Otherwise each branch advances using its own best failed
  proposal (shortest-replacement). Breadth stays at K.
- Dead-end: if a branch produces no diag_span_hash that differs from its
  current diag_span_hash — i.e. every failed proposal's new diagnostic hashes
  to the same span as the pre-edit state — that's a dead-end turn. Kill the
  branch; respawn one child from the parent state at elevated temperature.
  A branch that has already been respawned once and dead-ends again stays dead.
- Terminal:
  - SUCCESS: any proposal in any branch compiled OK.
  - ALL_BRANCHES_DEAD_END: after a turn, no live branch remains.
  - NO_PROPOSALS: a whole turn produced zero valid proposals across all live branches.
  - BUDGET_EXHAUSTED: token envelope exceeded or T turns completed with no success.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from repair.agent.observation import build_observation
from repair.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from repair.loop.terminal import (
    TerminalReason,
    apply_edit,
    is_trivial_deletion,
    within_span_window,
)
from foundation.types import Action, AgentState, TurnRecord, VerifierResult
from foundation.verifier.base import BaseVerifier


@dataclass
class BranchState:
    src: str                            # current full source for this branch.
    last_verify: VerifierResult         # verifier result that produced the current state.
    trajectory: list[TurnRecord] = field(default_factory=list)
    prev_span_hash: Optional[str] = None  # span_hash from the PREVIOUS turn's diagnostic.
    dead_end_respawned: bool = False    # True once after a respawn; another dead-end = death.
    temperature_boost: bool = False     # set for respawned children.
    alive: bool = True


@dataclass
class RunResult:
    ok: bool
    reason: TerminalReason
    final_src: str
    turns_used: int
    verifier_calls: int
    edits_applied: int                  # edits that actually changed src (not rejected).
    output_tokens_used: int = 0


def run_repair_loop(
    initial_src: str,
    compile_cmd: list[str],
    verifier: BaseVerifier,
    policy: Policy,
    ctx: PolicyContext,
    *,
    T: int = 5,
    K: int = 4,
    logical_path: str = "<instance>",
    token_envelope: Optional[int] = None,
) -> RunResult:
    """Run diagnostic repair search on one instance. See module docstring for semantics.

    `token_envelope`: if set, the loop terminates with BUDGET_EXHAUSTED when
    the cumulative policy-reported output tokens exceed this number. Used by
    the matched-budget protocol.
    """
    calls = 0
    edits = 0
    tokens = 0

    v0 = verifier.verify(initial_src, compile_cmd, logical_path=logical_path)
    calls += 1
    if v0.ok:
        return RunResult(True, TerminalReason.SUCCESS, initial_src, 0, calls, 0, 0)
    if v0.diag is None:
        return RunResult(False, TerminalReason.NO_PROPOSALS, initial_src, 0, calls, 0, 0)

    # Initial branch = single root; `prev_span_hash = None` so the first failed
    # proposal from turn 0 cannot trigger the dead-end comparison (needs history).
    branches: list[BranchState] = [
        BranchState(src=initial_src, last_verify=v0, prev_span_hash=None)
    ]

    for turn in range(T):
        # Enforce token envelope before generating more.
        if token_envelope is not None and tokens >= token_envelope:
            return RunResult(False, TerminalReason.BUDGET_EXHAUSTED,
                             branches[0].src if branches else initial_src,
                             turn, calls, edits, tokens)

        # Per turn: each live branch generates K proposals.
        proposal_sets: list[tuple[BranchState, list[EditProposal], VerifierResult]] = []
        any_proposed = False

        for b in branches:
            if not b.alive:
                continue
            v = b.last_verify
            assert v.diag is not None
            state = AgentState(
                src=b.src,
                diag=v.diag,
                trajectory=b.trajectory[-ctx.trajectory_window:],
                turn=turn,
            )
            local_ctx = _maybe_boost(ctx, b.temperature_boost, K)
            observation = build_observation(state, v.raw_stderr, local_ctx.signal_mode)

            pr: PolicyResult = policy.propose_edits(observation, local_ctx)
            tokens += pr.tokens_used
            # Enforce token envelope IMMEDIATELY after each accumulation, before
            # we let the loop proceed to further policy or verifier work. Otherwise
            # a single over-budget policy call could still fund all remaining
            # branch×proposal work in this turn.
            if token_envelope is not None and tokens > token_envelope:
                return RunResult(
                    False, TerminalReason.BUDGET_EXHAUSTED,
                    b.src, turn, calls, edits, tokens,
                )
            valid_proposals = [
                p for p in pr.proposals
                if _valid_proposal(b.src, p.action, v.diag.line, local_ctx)
            ][: local_ctx.k_proposals]
            if valid_proposals:
                any_proposed = True
            proposal_sets.append((b, valid_proposals, v))

        if not any_proposed:
            return RunResult(False, TerminalReason.NO_PROPOSALS,
                             branches[0].src if branches else initial_src,
                             turn, calls, edits, tokens)

        # Test each proposal; find SUCCESS candidates and record failed verifications.
        ok_candidates: list[tuple[int, str]] = []  # (len_replacement, new_src)
        per_branch_fails: list[list[tuple[EditProposal, str, VerifierResult]]] = []
        # per_branch_fails is aligned with proposal_sets order; one list per branch.

        for (_b, plist, _v) in proposal_sets:
            fails_this_branch: list[tuple[EditProposal, str, VerifierResult]] = []
            for p in plist:
                new_src = apply_edit(_b.src, p.action)
                if new_src == _b.src:
                    continue  # no-op edit; skip.
                vres = verifier.verify(new_src, compile_cmd, logical_path=logical_path)
                calls += 1
                edits += 1
                if vres.ok:
                    ok_candidates.append((len(p.action.replacement), new_src))
                else:
                    if vres.diag is not None:
                        fails_this_branch.append((p, new_src, vres))
                    # If vres.diag is None (compile failed but we couldn't parse
                    # the primary diag), drop the proposal entirely.
            per_branch_fails.append(fails_this_branch)

        if ok_candidates:
            ok_candidates.sort(key=lambda t: t[0])
            return RunResult(True, TerminalReason.SUCCESS, ok_candidates[0][1],
                             turn + 1, calls, edits, tokens)

        # No SUCCESS: advance each branch to a child state.
        next_branches: list[BranchState] = []

        is_first_turn_single_branch = (turn == 0 and len(branches) == 1)
        for (orig_branch, _plist, v), fails in zip(proposal_sets, per_branch_fails):
            if not orig_branch.alive:
                continue
            current_span_hash = v.diag.span_hash() if v.diag is not None else None
            if not fails:
                # Branch made proposals, but none applied successfully enough to get
                # a diag back. Treat as dead-end for this branch.
                next_branches.extend(_handle_dead_end(orig_branch, v, K))
                continue

            if is_first_turn_single_branch:
                # Fork: each valid failed proposal becomes its own child branch.
                # Prune to top K by shortest replacement.
                fails_sorted = sorted(fails, key=lambda f: len(f[0].action.replacement))[:K]
                for p, new_src, vres in fails_sorted:
                    new_hash = vres.diag.span_hash()
                    child = BranchState(
                        src=new_src,
                        last_verify=vres,
                        trajectory=orig_branch.trajectory + [TurnRecord(
                            diag_id=v.diag.diag_id,
                            diag_name=v.diag.diag_name,
                            edit_summary=p.edit_summary,
                        )],
                        prev_span_hash=current_span_hash,
                        dead_end_respawned=False,
                        temperature_boost=False,
                        alive=True,
                    )
                    # Dead-end check: new_hash == parent's current_span_hash
                    # AND the parent already had a matching prev_span_hash from
                    # its own previous turn. The first turn never has prev_span_hash.
                    if new_hash == current_span_hash and orig_branch.prev_span_hash == current_span_hash:
                        next_branches.extend(_handle_dead_end(orig_branch, v, K,
                                                              already_respawned=orig_branch.dead_end_respawned))
                    else:
                        next_branches.append(child)
                continue

            # Non-first-turn: advance this single branch using its best failed proposal.
            fails.sort(key=lambda f: len(f[0].action.replacement))
            best_p, best_src, best_vres = fails[0]
            new_hash = best_vres.diag.span_hash()
            # Dead-end triggers if BOTH (a) the new diag hashes same as current,
            # AND (b) the previous turn's diag already hashed the same — i.e. two
            # consecutive turns produced the same diagnostic for this branch.
            if (
                new_hash == current_span_hash
                and orig_branch.prev_span_hash == current_span_hash
            ):
                next_branches.extend(_handle_dead_end(orig_branch, v, K,
                                                      already_respawned=orig_branch.dead_end_respawned))
                continue

            next_branches.append(BranchState(
                src=best_src,
                last_verify=best_vres,
                trajectory=orig_branch.trajectory + [TurnRecord(
                    diag_id=v.diag.diag_id,
                    diag_name=v.diag.diag_name,
                    edit_summary=best_p.edit_summary,
                )],
                prev_span_hash=current_span_hash,
                dead_end_respawned=orig_branch.dead_end_respawned,
                temperature_boost=False,
                alive=True,
            ))

        # Cap to K live branches. If more children were produced (possible after
        # the first-turn fork), keep those whose failed replacements are shortest.
        branches = [b for b in next_branches if b.alive][:K]

        if not branches:
            return RunResult(False, TerminalReason.ALL_BRANCHES_DEAD_END,
                             initial_src, turn + 1, calls, edits, tokens)

    # Budget exhausted (T turns completed with no success).
    return RunResult(False, TerminalReason.BUDGET_EXHAUSTED,
                     branches[0].src, T, calls, edits, tokens)


def _valid_proposal(src: str, action: Action, diag_line: int, ctx: PolicyContext) -> bool:
    if not within_span_window(action, diag_line, ctx.span_window_lines):
        return False
    if is_trivial_deletion(src, action):
        return False
    return True


def _maybe_boost(ctx: PolicyContext, boost: bool, k: int) -> PolicyContext:
    """Return a possibly-boosted PolicyContext for respawned branches."""
    if not boost:
        return PolicyContext(
            signal_mode=ctx.signal_mode,
            span_window_lines=ctx.span_window_lines,
            trajectory_window=ctx.trajectory_window,
            k_proposals=k,
            temperature=ctx.temperature,
            max_tokens_per_call=ctx.max_tokens_per_call,
        )
    return PolicyContext(
        signal_mode=ctx.signal_mode,
        span_window_lines=ctx.span_window_lines,
        trajectory_window=ctx.trajectory_window,
        k_proposals=k,
        temperature=min(1.0, ctx.temperature + 0.2),
        max_tokens_per_call=ctx.max_tokens_per_call,
    )


def _handle_dead_end(
    parent: BranchState,
    parent_v: VerifierResult,
    k: int,
    *,
    already_respawned: bool = False,
) -> list[BranchState]:
    """Dead-end: kill the parent; if not already respawned once, spawn one at boosted temp."""
    if already_respawned:
        return []  # branch dies.
    # One respawn from the parent's pre-turn state, at elevated temperature.
    return [BranchState(
        src=parent.src,
        last_verify=parent_v,
        trajectory=list(parent.trajectory),
        prev_span_hash=parent.prev_span_hash,
        dead_end_respawned=True,
        temperature_boost=True,
        alive=True,
    )]
