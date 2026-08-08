"""The four measured rules — as a suggestion, never as a filter.

These began as a proposal to select airspace automatically, and the
measurements are what argued them down to a default. Selecting by rule needs a
size ceiling AND a distance ceiling AND a preview to tune them, all
site-dependent; that is more machinery than a checkbox list eyeballed once. So
what remains is a starting set the user adjusts.

Every rejection carries a reason. A picker that says "hidden: 334px is wider
than the panel" is usable; one that silently drops things is not.

Defaults derived from the 65nm box at 51.8850, 0.2350 on 2026-08-08:
CTR/CTA/TMZ reproduces the hand-curated editorial choice, a 50nm diagonal
(~110px, half the 109nm overview panel) cuts the seven enroute CTAs that are
larger on screen than the London TMA, and 50nm of distance cuts far-but-small
outliers like BOURNEMOUTH CTR at 43px and ~110nm away.
"""

DEFAULT_KINDS = ("CTR", "CTA", "OTHER/TMZ")
DEFAULT_MAX_DIAG_NM = 50.0
DEFAULT_MAX_DISTANCE_NM = 50.0


class SuggestRules:
    def __init__(self, kinds=DEFAULT_KINDS,
                 max_diag_nm=DEFAULT_MAX_DIAG_NM,
                 max_distance_nm=DEFAULT_MAX_DISTANCE_NM):
        self.kinds = tuple(kinds)
        self.max_diag_nm = max_diag_nm
        self.max_distance_nm = max_distance_nm

    def reject_reason(self, cand):
        """Why this would not be suggested, or None if it would."""
        if cand.kind not in self.kinds:
            return f"kind {cand.kind} not in {', '.join(self.kinds)}"
        if cand.diag_nm > self.max_diag_nm:
            return (f"{cand.diag_nm:.0f}nm wide, over the "
                    f"{self.max_diag_nm:.0f}nm limit — too wide to read as an "
                    f"enclosure")
        if cand.distance_nm > self.max_distance_nm:
            return (f"{cand.distance_nm:.0f}nm away, over the "
                    f"{self.max_distance_nm:.0f}nm limit — too far to matter")
        return None

    def accepts(self, cand):
        return self.reject_reason(cand) is None


def suggest(candidates, rules=None):
    """(accepted, [(rejected, reason)]) — every candidate accounted for."""
    rules = rules or SuggestRules()
    accepted, rejected = [], []
    for cand in candidates:
        reason = rules.reject_reason(cand)
        if reason is None:
            accepted.append(cand)
        else:
            rejected.append((cand, reason))
    return accepted, rejected
