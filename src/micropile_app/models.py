from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PileType(str, Enum):
    GROUTED = "微型灌注桩"
    HELICAL = "钢螺旋桩"


class PileTopConstraint(str, Enum):
    FREE = "铰接/自由"
    FIXED = "固接"


class PileTipCondition(str, Enum):
    SOIL = "桩端位于非岩石土层"
    ROCK_SURFACE = "桩端支承于基岩表面"
    ROCK_EMBEDDED = "桩端嵌固于基岩"


class SoilResistanceType(str, Enum):
    ROCK = "岩石（λ=0.8）"
    SAND = "砂土（λ=0.5）"
    COHESIVE_SILT = "黏性土或粉土（λ=0.7）"

    @property
    def uplift_factor(self) -> float:
        return {
            SoilResistanceType.ROCK: 0.8,
            SoilResistanceType.SAND: 0.5,
            SoilResistanceType.COHESIVE_SILT: 0.7,
        }[self]


class StabilitySoilType(str, Enum):
    COHESIVE = "黏性土（ξ=0.72）"
    SILTY = "粉质黏土或粉土（ξ=0.60）"
    SAND = "砂土（ξ=0.38）"
    CUSTOM = "特殊土（自定义ξ）"


HORIZONTAL_SOIL_CLASSES: dict[str, dict[PileType, tuple[float, float] | None]] = {
    "淤泥、淤泥质土、饱和湿陷性黄土": {
        PileType.HELICAL: (2.0, 4.5),
        PileType.GROUTED: (2.5, 6.0),
    },
    "流塑/软塑黏性土、松散粉细砂或填土": {
        PileType.HELICAL: (4.5, 6.0),
        PileType.GROUTED: (6.0, 14.0),
    },
    "可塑黏性土、中密填土或稍密细砂": {
        PileType.HELICAL: (6.0, 10.0),
        PileType.GROUTED: (14.0, 35.0),
    },
    "硬塑/坚硬黏性土、中密中粗砂或密实填土": {
        PileType.HELICAL: (10.0, 22.0),
        PileType.GROUTED: (35.0, 100.0),
    },
    "中密、密实砾砂或碎石类土": {
        PileType.HELICAL: None,
        PileType.GROUTED: (100.0, 300.0),
    },
}


@dataclass(frozen=True)
class LoadInput:
    compression_kn: float
    uplift_kn: float
    horizontal_kn: float
    consider_pile_self_weight: bool = False


@dataclass(frozen=True)
class SoilLayer:
    name: str
    uplift_factor: float
    thickness_m: float
    unit_weight_kn_m3: float
    beta_deg: float
    qsik_kpa: float
    qpk_kpa: float

@dataclass(frozen=True)
class CommonPileInput:
    diameter_m: float
    embedment_m: float
    above_ground_height_m: float
    top_constraint: PileTopConstraint
    allowable_displacement_mm: float
    width_reduction_factor: float
    horizontal_m_mn_m4: float
    horizontal_soil_class: str
    stability_soil_type: StabilitySoilType
    custom_xi: float | None = None
    pile_tip_condition: PileTipCondition = PileTipCondition.SOIL
    rock_strength_kpa: float | None = None


@dataclass(frozen=True)
class GroutedSection:
    concrete_modulus_mpa: float
    steel_modulus_mpa: float
    reinforcement_ratio: float
    cover_m: float


@dataclass(frozen=True)
class HelicalSection:
    wall_thickness_m: float
    steel_modulus_mpa: float
    blade_diameter_m: float
    blade_depths_m: tuple[float, ...]


@dataclass(frozen=True)
class MicropileInput:
    pile_type: PileType
    loads: LoadInput
    common: CommonPileInput
    soils: tuple[SoilLayer, ...]
    grouted: GroutedSection | None = None
    helical: HelicalSection | None = None
    project_name: str = ""


@dataclass(frozen=True)
class CheckResult:
    name: str
    demand_kn: float
    capacity_kn: float
    utilization: float
    passed: bool
    clause: str
    controlling_layer: str = ""
    note: str = ""


@dataclass
class CalculationResult:
    pile_type: PileType
    checks: dict[str, CheckResult]
    intermediates: dict[str, float | str]
    warnings: list[str] = field(default_factory=list)
    normalized_input: MicropileInput | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializable boundary reserved for the future report module."""

        data = asdict(self)
        data["pile_type"] = self.pile_type.value
        return _enum_values(data)


def _enum_values(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_enum_values(item) for item in value]
    return value


class InputValidationError(ValueError):
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("；".join(messages))
