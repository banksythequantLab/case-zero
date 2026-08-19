"""Structured output contracts for the CASE ZERO fleet.

Every agent returns validated JSON, not prose. This is what makes the
investigation graph machine-checkable and the provenance trail real.

EVIDENCE TIERS mirror ground_truth.json and are enforced end to end:
  DIRECT    - the corpus states it. Must carry a verbatim quote.
  INFERRED  - follows from corpus facts by stated reasoning. Must cite the facts.
  ABSENT    - would be needed but is NOT in the corpus. Can never support a
              confirmed finding. This is the tier that keeps the fleet honest.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Tier(str, Enum):
    DIRECT = "DIRECT"
    INFERRED = "INFERRED"
    ABSENT = "ABSENT"


class Citation(BaseModel):
    file: str = Field(description="corpus filename, exactly as given")
    quote: str = Field(description="verbatim span copied from that file - never paraphrase")


class Evidence(BaseModel):
    id: str
    summary: str = Field(description="what this evidence establishes, one sentence")
    tier: Tier
    citations: List[Citation] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    figures: List[str] = Field(default_factory=list, description="dollar amounts / percentages / counts")
    event_date: Optional[str] = Field(None, description="ISO date if the evidence is dated")


class Hypothesis(BaseModel):
    id: str
    claim: str = Field(description="a falsifiable statement about what happened")
    supporting: List[str] = Field(default_factory=list, description="evidence ids")
    contradicting: List[str] = Field(default_factory=list, description="evidence ids")
    confidence: float = Field(ge=0.0, le=1.0)
    unresolved: List[str] = Field(
        default_factory=list,
        description="what would have to be checked next to move this confidence")


class Verdict(BaseModel):
    hypothesis_id: str
    survives: bool
    confidence_after: float = Field(ge=0.0, le=1.0)
    attack: str = Field(description="the strongest argument AGAINST the hypothesis")
    unsupported_leap: bool = Field(
        description="true if the claim asserts something the corpus cannot establish")
    reasoning: str


class Lead(BaseModel):
    id: str
    question: str = Field(description="a specific, answerable investigative question")
    priority: float = Field(ge=0.0, le=1.0)
    assign_to: str = Field(description="evidence | hypothesis | skeptic")
    rationale: str


# ---- Batch wrappers passed to LlmAgent(output_schema=...) -----------------
#
# These MUST be real pydantic models, not hand-built dicts wrapping
# Model.model_json_schema(). A nested call puts pydantic's "$defs" block at the
# INNER schema's top level, while the google-genai schema transformer resolves
# "$ref" against the OUTER one - so the first live call died with
# `KeyError: 'Tier'` trying to find the enum definition. Declaring the wrapper
# as a model keeps every $ref and its $defs at the same level, where the
# transformer expects them.

class EvidenceBatch(BaseModel):
    evidence: List[Evidence]


class HypothesisBatch(BaseModel):
    hypotheses: List[Hypothesis]


class VerdictBatch(BaseModel):
    verdicts: List[Verdict]


class LeadBatch(BaseModel):
    leads: List[Lead]


EVIDENCE_BATCH = EvidenceBatch
HYPOTHESIS_BATCH = HypothesisBatch
VERDICT_BATCH = VerdictBatch
LEAD_BATCH = LeadBatch
