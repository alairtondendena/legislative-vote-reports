"""Domain records, one per row of each input CSV."""

from dataclasses import dataclass
from enum import IntEnum


class VoteType(IntEnum):
    """How a legislator voted, as encoded in ``vote_results.csv``."""

    YEA = 1
    NAY = 2


@dataclass(frozen=True, slots=True)
class Legislator:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Bill:
    id: int
    title: str
    sponsor_id: int


@dataclass(frozen=True, slots=True)
class Vote:
    id: int
    bill_id: int


@dataclass(frozen=True, slots=True)
class VoteResult:
    id: int
    legislator_id: int
    vote_id: int
    vote_type: int
    """Raw code from the file. Codes outside :class:`VoteType` (e.g. "Present") are kept here
    and handled by the tally, since they are legitimate votes rather than malformed rows."""
