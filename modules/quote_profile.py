"""
Quote Profile Data Model

Standardized data structure for all extracted document data.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class DriverProfile:
    """Data extracted for a single driver."""
    name: str = ""
    cdl_present: bool = False
    cdl_years: Optional[int] = None
    cdl_class: Optional[str] = None
    cdl_is_residential: bool = False
    mvr_present: bool = False
    mvr_years_covered: Optional[int] = None
    mvr_is_clean: bool = False


@dataclass
class LossRunProfile:
    """Data extracted from Loss Run document."""
    present: bool = False
    years_covered: Optional[int] = None
    is_clean: bool = False
    total_claims: int = 0


@dataclass
class IftasProfile:
    """Data extracted from IFTAS document."""
    present: bool = False
    is_registered: bool = False


@dataclass
class AppProfile:
    """Data extracted from New Venture Application."""
    present: bool = False
    ein_included: bool = False
    questions_filled: bool = False


@dataclass
class ApplicantProfile:
    """Applicant info from Blue Quote."""
    business_name: str = ""
    owner_name: str = ""
    owner_age: Optional[int] = None
    usdot: str = ""
    business_years: Optional[int] = None
    is_new_venture: bool = True
    industry_experience_years: Optional[int] = None


@dataclass
class UnitsProfile:
    """Vehicle/trailer info."""
    count: int = 0
    trailer_types: List[str] = field(default_factory=list)


@dataclass
class ConfidenceFlag:
    """A flag indicating extraction uncertainty."""
    field: str
    reason: str


@dataclass
class ExtractionConfidence:
    """Overall extraction confidence."""
    overall: str = "high"  # "high" or "low"
    flags: List[ConfidenceFlag] = field(default_factory=list)


@dataclass
class QuoteProfile:
    """Complete quote profile assembled from all 6 documents."""
    applicant: ApplicantProfile = field(default_factory=ApplicantProfile)
    commodity: str = ""
    coverages: List[str] = field(default_factory=list)
    units: UnitsProfile = field(default_factory=UnitsProfile)
    drivers: List[DriverProfile] = field(default_factory=list)
    loss_run: LossRunProfile = field(default_factory=LossRunProfile)
    iftas: IftasProfile = field(default_factory=IftasProfile)
    app: AppProfile = field(default_factory=AppProfile)
    documents_present: List[str] = field(default_factory=list)
    extraction_confidence: ExtractionConfidence = field(default_factory=ExtractionConfidence)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)
