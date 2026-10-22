from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from app.config import settings

Role = Literal["management", "employee", "admin"]
ROLES: tuple[Role, ...] = ("management", "employee", "admin")


class PermissionMatrix(BaseModel):
    roles: list[Role]
    capabilities: dict[str, dict[Role, Literal["allow", "deny"]]]

    @model_validator(mode="after")
    def every_cell_is_filled(self) -> "PermissionMatrix":
        # A missing cell must fail at startup, not silently default to allow or deny.
        for capability, cells in self.capabilities.items():
            missing = set(self.roles) - set(cells)
            if missing:
                raise ValueError(f"{capability}: no decision for {sorted(missing)}")
        return self

    def allows(self, role: Role, capability: str) -> bool:
        return self.capabilities[capability][role] == "allow"


def load_matrix(path: Path) -> PermissionMatrix:
    return PermissionMatrix.model_validate(yaml.safe_load(path.read_text()))


@cache
def matrix() -> PermissionMatrix:
    return load_matrix(settings.permission_matrix_path)
