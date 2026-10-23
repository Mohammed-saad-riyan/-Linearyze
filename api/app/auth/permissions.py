from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from app.config import settings

Role = Literal["management", "employee", "admin"]
ROLES: tuple[Role, ...] = ("management", "employee", "admin")
Cell = Literal["Y", "N", "TBD"]


class Capability(BaseModel):
    name: str
    management: Cell
    employee: Cell
    admin: Cell


class PermissionMatrix(BaseModel):
    roles: list[Role]
    capabilities: dict[str, Capability]
    poc_decisions: dict[str, dict[Role, Literal["Y", "N"]]] = {}

    @model_validator(mode="after")
    def decisions_only_resolve_tbd(self) -> "PermissionMatrix":
        # A PoC decision may settle an open (TBD) cell, never overrule one the SRS decided.
        for capability_id, cells in self.poc_decisions.items():
            for role in cells:
                if getattr(self.capabilities[capability_id], role) != "TBD":
                    raise ValueError(f"{capability_id}/{role} is not TBD in the SRS")
        return self

    def cell(self, role: Role, capability_id: str) -> Cell:
        return getattr(self.capabilities[capability_id], role)  # type: ignore[no-any-return]

    def allows(self, role: Role, capability_id: str) -> bool:
        cell = self.cell(role, capability_id)
        if cell == "TBD":
            return self.poc_decisions.get(capability_id, {}).get(role) == "Y"
        return cell == "Y"


def load_matrix(path: Path) -> PermissionMatrix:
    return PermissionMatrix.model_validate(yaml.safe_load(path.read_text()))


@cache
def matrix() -> PermissionMatrix:
    return load_matrix(settings.permission_matrix_path)
