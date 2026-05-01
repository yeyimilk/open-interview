"""Logical model catalog. Loads models.yaml and resolves logical -> provider/endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


Role = Literal["chat", "embedding"]


@dataclass(frozen=True)
class ModelEntry:
    logical_name: str
    role: Role
    provider: str
    endpoint: str
    model_id: str


class ModelCatalog:
    def __init__(self, entries: dict[tuple[Role, str], ModelEntry], defaults: dict[Role, str]):
        self._entries = entries
        self._defaults = defaults

    def resolve(self, role: Role, logical_name: str | None) -> ModelEntry:
        name = logical_name or self._defaults.get(role)
        if name is None:
            raise KeyError(f"no default model configured for role {role!r}")
        try:
            return self._entries[(role, name)]
        except KeyError as e:
            raise KeyError(f"unknown logical model: role={role} name={name}") from e

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ModelCatalog":
        data = yaml.safe_load(Path(path).read_text())
        entries: dict[tuple[Role, str], ModelEntry] = {}
        defaults: dict[Role, str] = {}
        for role in ("chat", "embedding"):
            section = data.get(role) or {}
            if "default" in section:
                defaults[role] = section["default"]  # type: ignore[index]
            for name, body in (section.get("models") or {}).items():
                entries[(role, name)] = ModelEntry(  # type: ignore[index]
                    logical_name=name,
                    role=role,  # type: ignore[arg-type]
                    provider=body["provider"],
                    endpoint=body["endpoint"],
                    model_id=body["model_id"],
                )
        return cls(entries, defaults)
