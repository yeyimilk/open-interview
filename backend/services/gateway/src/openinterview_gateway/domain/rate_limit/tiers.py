from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TierLimits:
    name: str
    rate_limit_rpm: int


class TierCatalog:
    def __init__(self, tiers: dict[str, TierLimits], default: str = "free") -> None:
        self._tiers = tiers
        self._default = default

    def get(self, name: str) -> TierLimits:
        return self._tiers.get(name) or self._tiers[self._default]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TierCatalog":
        data = yaml.safe_load(Path(path).read_text()) or {}
        tiers: dict[str, TierLimits] = {}
        for name, body in (data.get("tiers") or {}).items():
            tiers[name] = TierLimits(name=name, rate_limit_rpm=int(body["rate_limit_rpm"]))
        if "free" not in tiers:
            tiers["free"] = TierLimits(name="free", rate_limit_rpm=20)
        return cls(tiers, default="free")
