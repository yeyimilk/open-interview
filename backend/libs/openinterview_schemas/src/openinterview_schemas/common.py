from __future__ import annotations

from enum import Enum


class Level(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    principal = "principal"
    tech_lead = "tech_lead"


class Position(str, Enum):
    swe_generic = "swe_generic"
    applied_ai = "applied_ai"


class Category(str, Enum):
    coding = "coding"
    system_design = "system_design"
    ml = "ml"
    applied_ai = "applied_ai"
    behavioral = "behavioral"
    project_deepdive = "project_deepdive"


class Source(str, Enum):
    private = "private"
    common = "common"
