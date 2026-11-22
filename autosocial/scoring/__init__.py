"""Professor scoring engine.

Public API:
    score_professor_fit                – research-fit 0-100
    score_professor_interaction_priority – interaction priority 0-900
    score_note_priority_heuristic      – keyword-based note adjustment
"""

from .fit import score_professor_fit
from .priority import score_note_priority_heuristic, score_professor_interaction_priority
from .weights import (
    NOTE_PRIORITY_NEGATIVE,
    NOTE_PRIORITY_POSITIVE,
    STAGE_INTERACTION_META,
)

__all__ = [
    "NOTE_PRIORITY_NEGATIVE",
    "NOTE_PRIORITY_POSITIVE",
    "STAGE_INTERACTION_META",
    "score_note_priority_heuristic",
    "score_professor_fit",
    "score_professor_interaction_priority",
]
