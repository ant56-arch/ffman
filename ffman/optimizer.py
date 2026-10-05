"""Pick the highest-projected legal lineup.

Solved exactly as an assignment problem (slots x players) with the Hungarian
algorithm, so odd slot combinations like REC_FLEX + WRRB_FLEX are handled
correctly, not just the usual nested QB/RB/WR/TE/FLEX case.
"""

from __future__ import annotations

from .models import Lineup, Player, Team

_INELIGIBLE = 1e9
_EMPTY = 1e6  # leaving a slot empty is only chosen when nobody can fill it
_LOCKED = 1e7  # pins a started player to the slot they're already in
# Tiny tie-breakers so equal projections never produce pointless swaps.
_SAME_SLOT_BONUS = 1e-3
_STARTER_BONUS = 5e-4


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Min-cost assignment of every row to a distinct column (rows <= cols)."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            assignment[p[j] - 1] = j - 1
    return assignment


def optimal_lineup(team: Team) -> Lineup:
    slots, roster = team.slots, team.roster
    if not slots:
        return Lineup([], [])
    current_slot = {
        p.id: slot for slot, p in zip(team.current.slots, team.current.players) if p
    }
    # Players whose game has started can't move: starters stay in their exact slot,
    # bench players stay on the bench. (current.slots is aligned with team.slots.)
    locked_at = {
        p.id: i for i, p in enumerate(team.current.players) if p is not None and p.locked
    }

    # One column per player plus one "empty" column per slot.
    cost: list[list[float]] = []
    for i, slot in enumerate(slots):
        row = []
        for player in roster:
            if player.locked:
                row.append(-_LOCKED if locked_at.get(player.id) == i else _INELIGIBLE)
                continue
            if slot not in player.eligible:
                row.append(_INELIGIBLE)
                continue
            weight = player.effective_projection
            if player.id in current_slot:
                weight += _STARTER_BONUS
                if current_slot[player.id] == slot:
                    weight += _SAME_SLOT_BONUS
            row.append(-weight)
        row.extend([_EMPTY] * len(slots))
        cost.append(row)

    assignment = _hungarian(cost)
    chosen: list[Player | None] = []
    for col in assignment:
        chosen.append(roster[col] if col < len(roster) else None)
    return Lineup(list(slots), chosen)
