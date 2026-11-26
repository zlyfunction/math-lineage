"""Pydantic API schemas for MathLineage."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field


class VerifyDissertationRequest(BaseModel):
    identifier: str = Field(..., min_length=2, description="DOI, HAL ID, theses.fr ID/URL, or MIT DSpace Handle/URL")
    source_hint: Optional[str] = Field(None, description="Optional hint: datacite | hal | theses_fr | mit_dspace")


class LiveRepoSearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    source: str = Field("all", description="all | hal | theses_fr | mit_dspace | datacite")
    limit: int = Field(8, ge=1, le=25)


class SubmissionCreateRequest(BaseModel):
    scholar_name: str = Field(..., min_length=2)
    advisors: List[str] = Field(..., min_length=1)
    university: str = ""
    country: str = ""
    degree: str = "Ph.D."
    year: Optional[int] = None
    thesis_title: str = Field(..., min_length=3)
    thesis_title_en: str = ""
    msc_code: str = ""
    source_repo: str = Field(..., min_length=2)
    source_record_id: str = Field(..., min_length=1)
    doi: str = ""
    landing_url: str = Field(..., min_length=8)
    pdf_url: str = ""
    raw_metadata_json: str = "{}"
    submitter_note: str = ""


class ReviewActionRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    review_note: str = ""


class HarvestRequest(BaseModel):
    source: str = Field(..., pattern="^(hal|theses_fr|mit_dspace|datacite|nyu_courant)$")
    query: str = ""
    limit: int = Field(25, ge=5, le=100)


class VerifiedDissertationCandidate(BaseModel):
    scholar_name: str
    advisors: List[str]
    university: str
    country: str
    department: str = ""
    degree: str = "Ph.D."
    year: Optional[int] = None
    thesis_title: str
    thesis_title_en: str = ""
    source_repo: str
    source_record_id: str
    doi: str = ""
    landing_url: str
    pdf_url: str = ""
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    existing_scholar_match: Optional[dict[str, Any]] = None
    matched_advisors: List[dict[str, Any]] = Field(default_factory=list)
    verification_notes: List[str] = Field(default_factory=list)
