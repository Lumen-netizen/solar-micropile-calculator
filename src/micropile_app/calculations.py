from __future__ import annotations

import math
from collections.abc import Iterable

from .models import (
    CalculationResult,
    CheckResult,
    HORIZONTAL_SOIL_CLASSES,
    InputValidationError,
    MicropileInput,
    PileTopConstraint,
    PileTipCondition,
    PileType,
    SoilLayer,
    StabilitySoilType,
)


NU_X_TABLE: dict[PileTopConstraint, dict[float, float]] = {
    PileTopConstraint.FREE: {
        2.4: 3.526,
        2.6: 3.163,
        2.8: 2.905,
        3.0: 2.727,
        3.5: 2.502,
        4.0: 2.441,
    },
    PileTopConstraint.FIXED: {
        2.4: 1.095,
        2.6: 1.079,
        2.8: 1.055,
        3.0: 1.028,
        3.5: 0.970,
        4.0: 0.940,
    },
}

XI_DEFAULTS = {
    StabilitySoilType.COHESIVE: 0.72,
    StabilitySoilType.SILTY: 0.60,
    StabilitySoilType.SAND: 0.38,
}

REINFORCED_CONCRETE_UNIT_WEIGHT_KN_M3 = 25.0
STEEL_UNIT_WEIGHT_KN_M3 = 78.0


def micro_short_pile_scope_exceedances(data: MicropileInput) -> list[str]:
    """Return GB 51101-2016 2.1.7 definition exceedances without blocking calculation."""

    messages: list[str] = []
    common = data.common
    if common.diameter_m > 0.3 + 1e-9:
        messages.append(f"桩身外径 d={common.diameter_m * 1000:g} mm，大于300 mm")
    if common.embedment_m > 5.0 + 1e-9:
        messages.append(f"地下计算埋深（入土桩长）hₜ={common.embedment_m:g} m，大于5 m")
    return messages


def calculate(data: MicropileInput) -> CalculationResult:
    errors = _validate(data)
    if errors:
        raise InputValidationError(errors)

    warnings: list[str] = []
    common = data.common
    loads = data.loads
    d = common.diameter_m
    if d < 0.3:
        warnings.append(
            "桩径小于300 mm；JGJ 94要求适当降低计算宽度，请确认小直径折减系数。"
        )
    _check_horizontal_m_range(data, warnings)

    if data.pile_type is PileType.GROUTED:
        compression_capacity, uplift_capacity, vertical_values = _grouted_vertical(data)
        ei, section_values = _grouted_ei(data)
    else:
        compression_capacity, uplift_capacity, vertical_values, helix_warnings = _helical_vertical(data)
        warnings.extend(helix_warnings)
        ei, section_values = _steel_ei(data)

    pile_self_weight, self_weight_values = _pile_self_weight(data)
    adopted_self_weight = pile_self_weight if loads.consider_pile_self_weight else 0.0
    net_uplift = max(0.0, loads.uplift_kn - adopted_self_weight)
    self_weight_values["抗拔验算采用单桩自重 Gp (kN)"] = adopted_self_weight
    self_weight_values["抗拔验算净作用 Tk-Gp (kN)"] = net_uplift

    horizontal_capacity, horizontal_values = _horizontal_capacity(data, ei, section_values)
    stability_capacity, stability_values = _stability_capacity(data)

    # These labels support the concise result cards, but are not general-purpose
    # calculation intermediates and therefore are removed before serialization.
    end_layer = str(vertical_values.pop("抗压控制土层", data.soils[-1].name))
    pullout_layer = str(
        vertical_values.pop(
            "抗拔控制土层",
            max(
                data.soils,
                key=lambda layer: layer.uplift_factor * layer.qsik_kpa * layer.thickness_m,
            ).name,
        )
    )

    if data.pile_type is PileType.GROUTED:
        compression_clause = "NB/T 10115-2018 8.3.3～8.3.5；GB 51101-2016 5.3.5、5.3.7"
        uplift_clause = "GB 51101-2016 5.3.5、5.3.8"
    else:
        compression_clause = "GB 51101-2016 5.3.5、5.3.9"
        uplift_clause = "GB 51101-2016 5.3.5、5.3.10"

    checks = {
        "compression": _check(
            "抗压验算",
            loads.compression_kn,
            compression_capacity,
            compression_clause,
            end_layer,
        ),
        "uplift": _check(
            "抗拔验算",
            net_uplift,
            uplift_capacity,
            uplift_clause,
            pullout_layer,
            (
                "按实际计算单桩自重并从桩顶拔力中扣除。"
                if loads.consider_pile_self_weight
                else "本程序保守取单桩自重Gp=0。"
            ),
        ),
        "horizontal": _check(
            "水平承载力验算",
            loads.horizontal_kn,
            horizontal_capacity,
            "NB/T 10115-2018 8.3.7～8.3.8；GB 51101-2016 5.3.11；"
            "JGJ 94-2008 5.7.2、5.7.5、附录C表C.0.3-1及C.0.2",
            common.horizontal_soil_class,
        ),
        "stability": _check(
            "整体稳定（抗倾覆）验算",
            1.1 * loads.horizontal_kn,
            stability_capacity,
            "NB/T 10115-2018 8.3.15",
            common.stability_soil_type.value,
            "整体稳定验算系数KMw=1.1，验算水平力按1.1HMik计。",
        ),
    }

    intermediates: dict[str, float | str] = {}
    intermediates.update(vertical_values)
    intermediates.update(self_weight_values)
    intermediates.update(section_values)
    intermediates.update(horizontal_values)
    intermediates.update(stability_values)
    return CalculationResult(
        pile_type=data.pile_type,
        checks=checks,
        intermediates=intermediates,
        warnings=warnings,
        normalized_input=data,
    )


def _pile_self_weight(data: MicropileInput) -> tuple[float, dict[str, float | str]]:
    """Return total pile self-weight for the full above- and below-ground length."""

    common = data.common
    total_length = common.above_ground_height_m + common.embedment_m
    if data.pile_type is PileType.GROUTED:
        volume = math.pi * common.diameter_m**2 / 4 * total_length
        unit_weight = REINFORCED_CONCRETE_UNIT_WEIGHT_KN_M3
        basis = "钢筋混凝土圆形实心截面，重度25 kN/m³"
    else:
        assert data.helical is not None
        inner_diameter = common.diameter_m - 2 * data.helical.wall_thickness_m
        volume = math.pi * (common.diameter_m**2 - inner_diameter**2) / 4 * total_length
        unit_weight = STEEL_UNIT_WEIGHT_KN_M3
        basis = "钢管空心圆截面，钢材重度78 kN/m³，忽略螺旋叶片重量"
    self_weight = volume * unit_weight
    return self_weight, {
        "桩身总长度 h0+ht (m)": total_length,
        "桩自重计算体积 Vp (m³)": volume,
        "桩身材料重度 γp (kN/m³)": unit_weight,
        "计算单桩自重 Gp (kN)": self_weight,
        "桩自重计算说明": basis,
    }


def _check(
    name: str,
    demand: float,
    capacity: float,
    clause: str,
    controlling_layer: str,
    note: str = "",
) -> CheckResult:
    utilization = demand / capacity if capacity > 0 else math.inf
    return CheckResult(
        name=name,
        demand_kn=demand,
        capacity_kn=capacity,
        utilization=utilization,
        passed=demand <= capacity + 1e-9,
        clause=clause,
        controlling_layer=controlling_layer,
        note=note,
    )


def _validate(data: MicropileInput) -> list[str]:
    errors = _validate_finite_values(data)
    # NaN can bypass ordinary range comparisons and Infinity can contaminate
    # subsequent summations. Report all non-finite fields together, then stop
    # before carrying out the remaining numerical checks.
    if errors:
        return errors

    common = data.common
    loads = data.loads
    if any(value < 0 for value in (loads.compression_kn, loads.uplift_kn, loads.horizontal_kn)):
        errors.append("抗压、抗拔和水平作用值不得为负数")
    if loads.horizontal_kn > 0 and common.above_ground_height_m <= 0:
        errors.append("水平力大于0时，桩高出地面的高度h0必须大于0")
    if common.above_ground_height_m < 0:
        errors.append("桩高出地面的高度h0不得为负数")
    if common.diameter_m <= 0 or common.embedment_m <= 0:
        errors.append("桩径和计算埋深必须大于0")
    if common.allowable_displacement_mm not in (6.0, 10.0):
        errors.append("允许水平位移只能取6 mm或10 mm")
    if not 0 < common.width_reduction_factor <= 1:
        errors.append("小直径计算宽度折减系数应大于0且不大于1")
    if common.horizontal_m_mn_m4 <= 0:
        errors.append("水平抗力比例系数m必须大于0")
    if common.horizontal_soil_class not in HORIZONTAL_SOIL_CLASSES:
        errors.append("水平土类别无效")
    if common.pile_tip_condition is PileTipCondition.ROCK_SURFACE:
        if common.rock_strength_kpa is None or common.rock_strength_kpa < 1000:
            errors.append("桩端支承于基岩表面时，岩石饱和单轴抗压强度标准值不应小于1000 kPa")
    if common.stability_soil_type is StabilitySoilType.CUSTOM:
        if common.custom_xi is None or common.custom_xi <= 0:
            errors.append("特殊土必须输入正的土的侧压力系数ξ")
    if not data.soils:
        errors.append("至少需要一个土层")
    for index, layer in enumerate(data.soils, start=1):
        if not layer.name.strip():
            errors.append(f"第{index}层土名称不能为空")
        if layer.thickness_m <= 0:
            errors.append(f"第{index}层土厚度必须大于0")
        if min(layer.unit_weight_kn_m3, layer.beta_deg, layer.qsik_kpa, layer.qpk_kpa) < 0:
            errors.append(f"第{index}层土参数不得为负数")
        if layer.uplift_factor not in (0.5, 0.7, 0.8):
            errors.append(f"第{index}层抗拔系数λ只能取0.5、0.7或0.8")
        if layer.beta_deg >= 90:
            errors.append(f"第{index}层等代内摩擦角必须小于90°")
    if data.soils and sum(layer.thickness_m for layer in data.soils) < common.embedment_m - 1e-6:
        errors.append("土层总厚度不得小于地下计算埋深ht，否则无法覆盖完整桩长")

    if data.pile_type is PileType.GROUTED:
        section = data.grouted
        if section is None:
            errors.append("缺少微型灌注桩截面参数")
        else:
            if min(section.concrete_modulus_mpa, section.steel_modulus_mpa) <= 0:
                errors.append("混凝土和钢筋弹性模量必须大于0")
            if section.reinforcement_ratio < 0.0065:
                errors.append("配筋率小于0.65%，超出本App位移控制验算范围")
            if section.cover_m < 0.035 - 1e-12:
                errors.append("微型灌注桩主筋保护层厚度不应小于35 mm（GB 51101-2016第5.4.8条）")
            if 2 * section.cover_m >= common.diameter_m:
                errors.append("保护层厚度应小于桩半径")
    else:
        section = data.helical
        if section is None:
            errors.append("缺少钢螺旋桩截面和叶片参数")
        else:
            if section.steel_modulus_mpa <= 0:
                errors.append("钢材弹性模量必须大于0")
            if section.wall_thickness_m <= 0 or 2 * section.wall_thickness_m >= common.diameter_m:
                errors.append("钢管壁厚应大于0且小于钢管半径")
            if section.blade_diameter_m <= common.diameter_m:
                errors.append("叶片直径必须大于钢管外径")
            if not section.blade_depths_m:
                errors.append("至少需要一道螺旋叶片")
            else:
                if any(depth <= 0 for depth in section.blade_depths_m):
                    errors.append("叶片埋深必须大于0")
                if tuple(sorted(section.blade_depths_m)) != section.blade_depths_m or len(set(section.blade_depths_m)) != len(section.blade_depths_m):
                    errors.append("叶片埋深必须严格递增")
                if section.blade_depths_m[-1] >= common.embedment_m:
                    errors.append("最下层叶片埋深必须小于地下计算埋深ht，桩尖应位于叶片以下")
    return errors


def _validate_finite_values(data: MicropileInput) -> list[str]:
    """Reject NaN and positive/negative infinity at the calculation boundary."""

    common = data.common
    loads = data.loads
    values: list[tuple[str, float]] = [
        ("桩顶压力 N_Mk", loads.compression_kn),
        ("桩顶拔力 T_k", loads.uplift_kn),
        ("桩顶水平力 H_Mik", loads.horizontal_kn),
        ("桩身外径 d", common.diameter_m),
        ("地下计算埋深 h_t", common.embedment_m),
        ("桩高出地面的高度 h_0", common.above_ground_height_m),
        ("地面处允许水平位移 x_0a", common.allowable_displacement_mm),
        ("小直径计算宽度折减系数", common.width_reduction_factor),
        ("水平抗力比例系数 m", common.horizontal_m_mn_m4),
    ]
    if common.custom_xi is not None:
        values.append(("土的侧压力系数 ξ", common.custom_xi))
    if common.rock_strength_kpa is not None:
        values.append(("岩石饱和单轴抗压强度标准值 f_rk", common.rock_strength_kpa))

    for index, layer in enumerate(data.soils, start=1):
        prefix = f"第{index}层土"
        values.extend(
            (
                (f"{prefix}厚度 l_i", layer.thickness_m),
                (f"{prefix}重度 γ", layer.unit_weight_kn_m3),
                (f"{prefix}等代内摩擦角 β", layer.beta_deg),
                (f"{prefix}桩侧极限阻力标准值 q_sik", layer.qsik_kpa),
                (f"{prefix}桩端极限阻力标准值 q_pk", layer.qpk_kpa),
                (f"{prefix}抗拔系数 λ", layer.uplift_factor),
            )
        )

    if data.pile_type is PileType.GROUTED and data.grouted is not None:
        section = data.grouted
        values.extend(
            (
                ("混凝土弹性模量 E_c", section.concrete_modulus_mpa),
                ("钢筋弹性模量 E_s", section.steel_modulus_mpa),
                ("现有配筋率 ρ_g", section.reinforcement_ratio),
                ("保护层厚度 c", section.cover_m),
            )
        )
    elif data.pile_type is PileType.HELICAL and data.helical is not None:
        section = data.helical
        values.extend(
            (
                ("钢管壁厚 t", section.wall_thickness_m),
                ("钢材弹性模量 E_s", section.steel_modulus_mpa),
                ("叶片直径 D", section.blade_diameter_m),
            )
        )
        values.extend(
            (f"第{index}道叶片埋深", depth)
            for index, depth in enumerate(section.blade_depths_m, start=1)
        )

    return [f"{name}必须为有限数值" for name, value in values if not math.isfinite(value)]


def _grouted_vertical(data: MicropileInput) -> tuple[float, float, dict[str, float | str]]:
    d = data.common.diameter_m
    segments = list(_embedded_segments(data.soils, data.common.embedment_m))
    side = math.pi * d * sum(layer.qsik_kpa * length for layer, length in segments)
    tip_layer = _soil_at_depth(data.soils, data.common.embedment_m)
    tip = tip_layer.qpk_kpa * math.pi * d**2 / 4
    uplift = math.pi * d * sum(
        layer.uplift_factor * layer.qsik_kpa * length for layer, length in segments
    )
    pullout_layer = max(segments, key=lambda item: item[0].uplift_factor * item[0].qsik_kpa * item[1])[0].name
    return (side + tip) / 2, uplift / 2, {
        "竖向总极限侧阻力 Qsk (kN)": side,
        "桩端极限阻力 Qpk (kN)": tip,
        "抗压极限承载力 Quk (kN)": side + tip,
        "抗拔极限承载力 Tuk (kN)": uplift,
        "抗压控制土层": tip_layer.name,
        "抗拔控制土层": pullout_layer,
    }


def _helical_vertical(
    data: MicropileInput,
) -> tuple[float, float, dict[str, float | str], list[str]]:
    assert data.helical is not None
    section = data.helical
    d = data.common.diameter_m
    D = section.blade_diameter_m
    boundaries = _integration_boundaries(data)
    compression_side = 0.0
    uplift = 0.0
    contributions: dict[str, float] = {layer.name: 0.0 for layer in data.soils}
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start <= 1e-12:
            continue
        midpoint = (start + end) / 2
        layer = _soil_at_depth(data.soils, midpoint)
        length = end - start
        uc = effective_circumference(midpoint, d, D, section.blade_depths_m, "compression")
        ut = effective_circumference(midpoint, d, D, section.blade_depths_m, "uplift")
        compression_side += uc * layer.qsik_kpa * length
        pull = layer.uplift_factor * ut * layer.qsik_kpa * length
        uplift += pull
        contributions[layer.name] += pull

    blade_area = math.pi * (D**2 - d**2) / 4
    lowest_blade_depth = section.blade_depths_m[-1]
    blade_layer = _soil_at_depth(data.soils, lowest_blade_depth)
    tip = blade_layer.qpk_kpa * blade_area
    warnings: list[str] = []
    if len(section.blade_depths_m) not in (2, 3):
        warnings.append("工程中钢螺旋桩通常设置2～3片叶片，请核实施际叶片数量。")
    for upper, lower in zip(section.blade_depths_m, section.blade_depths_m[1:]):
        ratio = (lower - upper) / D
        if ratio < 3 or ratio > 4:
            warnings.append(f"叶片间距比{ratio:.2f}超出GB 51101建议的3～4范围。")
    values: dict[str, float | str] = {
        "螺旋桩有效侧阻力 (kN)": compression_side,
        "叶片净投影面积 AD (m²)": blade_area,
        "叶片端阻力 (kN)": tip,
        "最下层叶片埋深 (m)": lowest_blade_depth,
        "桩尖埋深 ht (m)": data.common.embedment_m,
        "最下层叶片至桩尖距离 (m)": data.common.embedment_m - lowest_blade_depth,
        "抗压极限承载力 Quk (kN)": compression_side + tip,
        "抗拔极限承载力 Tuk (kN)": uplift,
        "抗压控制土层": blade_layer.name,
        "抗拔控制土层": max(contributions, key=contributions.get),
    }
    return (compression_side + tip) / 2, uplift / 2, values, warnings


def _integration_boundaries(data: MicropileInput) -> list[float]:
    assert data.helical is not None
    section = data.helical
    D = section.blade_diameter_m
    h = data.common.embedment_m
    points = {0.0, h, *section.blade_depths_m}
    depth = 0.0
    for layer in data.soils:
        depth += layer.thickness_m
        points.add(depth)
    top = section.blade_depths_m[0]
    points.update((top - D, top - 2 * D))
    for upper, lower in zip(section.blade_depths_m, section.blade_depths_m[1:]):
        points.update((upper + D, upper + 3 * D, lower - D, lower - 3 * D))
    return sorted(min(h, max(0.0, point)) for point in points)


def effective_circumference(
    depth_m: float,
    shaft_diameter_m: float,
    blade_diameter_m: float,
    blade_depths_m: tuple[float, ...],
    mode: str,
) -> float:
    """GB 51101 tables 5.3.9/5.3.10 piecewise effective circumference."""

    if mode not in {"compression", "uplift"}:
        raise ValueError("mode must be compression or uplift")
    d, D = shaft_diameter_m, blade_diameter_m
    pi_d, pi_D = math.pi * d, math.pi * D
    top = blade_depths_m[0]
    if depth_m < top:
        if mode == "compression":
            return 0.0 if depth_m >= top - D else pi_d
        return pi_D if depth_m >= top - 2 * D else pi_d

    for upper, lower in zip(blade_depths_m, blade_depths_m[1:]):
        if upper <= depth_m < lower:
            spacing = lower - upper
            if spacing <= 3 * D:
                return pi_D
            if spacing < 4 * D:
                if mode == "compression":
                    return pi_D if depth_m < upper + 3 * D else 0.0
                return 0.0 if depth_m < upper + (spacing - 3 * D) else pi_D
            if mode == "compression":
                if depth_m < upper + 3 * D:
                    return pi_D
                if depth_m >= lower - D:
                    return 0.0
                return pi_d
            if depth_m < upper + D:
                return 0.0
            if depth_m >= lower - 3 * D:
                return pi_D
            return pi_d
    return 0.0


def _soil_at_depth(soils: Iterable[SoilLayer], depth_m: float) -> SoilLayer:
    cumulative = 0.0
    last: SoilLayer | None = None
    for layer in soils:
        last = layer
        cumulative += layer.thickness_m
        if depth_m < cumulative + 1e-9:
            return layer
    assert last is not None
    return last


def _embedded_segments(soils: Iterable[SoilLayer], embedment_m: float) -> Iterable[tuple[SoilLayer, float]]:
    depth = 0.0
    for layer in soils:
        layer_bottom = depth + layer.thickness_m
        used_length = max(0.0, min(layer_bottom, embedment_m) - depth)
        if used_length > 1e-12:
            yield layer, used_length
        depth = layer_bottom
        if depth >= embedment_m - 1e-12:
            break


def _grouted_ei(data: MicropileInput) -> tuple[float, dict[str, float | str]]:
    assert data.grouted is not None
    d = data.common.diameter_m
    section = data.grouted
    d0 = d - 2 * section.cover_m
    alpha_e = section.steel_modulus_mpa / section.concrete_modulus_mpa
    w0 = math.pi * d * (
        d**2 + 2 * (alpha_e - 1) * section.reinforcement_ratio * d0**2
    ) / 32
    i0 = w0 * d0 / 2
    ei = 0.85 * section.concrete_modulus_mpa * 1000 * i0
    return ei, {
        "扣除保护层直径 d0 (m)": d0,
        "钢筋与混凝土弹模比 αE": alpha_e,
        "换算截面模量 W0 (m³)": w0,
        "换算惯性矩 I0 (m⁴)": i0,
        "桩身抗弯刚度 EI (kN·m²)": ei,
    }


def _steel_ei(data: MicropileInput) -> tuple[float, dict[str, float | str]]:
    assert data.helical is not None
    d = data.common.diameter_m
    t = data.helical.wall_thickness_m
    inner = d - 2 * t
    inertia = math.pi * (d**4 - inner**4) / 64
    ei = data.helical.steel_modulus_mpa * 1000 * inertia
    return ei, {
        "钢管内径 (m)": inner,
        "钢管截面惯性矩 I (m⁴)": inertia,
        "桩身抗弯刚度 EI (kN·m²)": ei,
    }


def _horizontal_capacity(
    data: MicropileInput, ei: float, section_values: dict[str, float | str]
) -> tuple[float, dict[str, float | str]]:
    if data.loads.horizontal_kn == 0:
        return math.inf, {"水平验算说明": "水平力为0，无需验算"}
    common = data.common
    d = common.diameter_m
    b0_base = 0.9 * (1.5 * d + 0.5) if d <= 1 else 0.9 * (d + 1)
    b0 = b0_base * (common.width_reduction_factor if d < 0.3 else 1.0)
    m_kn_m4 = common.horizontal_m_mn_m4 * 1000
    alpha = (m_kn_m4 * b0 / ei) ** 0.2
    alpha_h = alpha * common.embedment_m
    displacement_m = common.allowable_displacement_mm / 1000
    values: dict[str, float | str] = {
        "JGJ基础计算宽度 b0,base (m)": b0_base,
        "折减后计算宽度 b0 (m)": b0,
        "水平变形系数 α (1/m)": alpha,
        "换算埋深 αh": alpha_h,
        "允许水平位移 x0a (mm)": common.allowable_displacement_mm,
    }
    inertia = section_values.get("换算惯性矩 I0 (m⁴)", section_values.get("钢管截面惯性矩 I (m⁴)"))
    if not isinstance(inertia, (int, float)):
        raise InputValidationError(["缺少附录C计算所需的桩端截面惯性矩"])
    compliance, appendix_values = _appendix_c_ground_compliance(data, ei, b0, float(inertia))
    capacity = 0.75 * displacement_m / compliance
    actual_displacement_mm = compliance * data.loads.horizontal_kn * 1000
    ground_moment = float(appendix_values["单位水平力地面处弯矩 M0 (kN·m/kN)"]) * data.loads.horizontal_kn
    values.update(appendix_values)
    values.update({
        "水平验算方法": "JGJ 94附录C有限长度桩m法",
        "单位水平力地面处位移 δx0 (m/kN)": compliance,
        "标准组合水平力下地面处位移 x0k (mm)": actual_displacement_mm,
        "标准组合水平力下地面处弯矩 M0k (kN·m)": ground_moment,
        "水平承载力特征值 Rha (kN)": capacity,
    })
    return capacity, values


def _appendix_c_ground_compliance(
    data: MicropileInput, ei: float, b0: float, inertia: float
) -> tuple[float, dict[str, float | str]]:
    """Return ground-level displacement per unit head load by Appendix C m-method."""

    common = data.common
    h0, h = common.above_ground_height_m, common.embedment_m
    m_kn_m4 = common.horizontal_m_mn_m4 * 1000
    alpha = (m_kn_m4 * b0 / ei) ** 0.2
    alpha_h = alpha * h
    transfer = _beam_transfer_matrix(h0 + h, h0, ei, m_kn_m4 * b0)
    if common.pile_tip_condition is PileTipCondition.ROCK_EMBEDDED:
        bottom_rows = [transfer[0], transfer[1]]
        c0_kn_m3 = math.inf
        rotational_stiffness = math.inf
    else:
        if common.pile_tip_condition is PileTipCondition.SOIL:
            c0_kn_m3 = m_kn_m4 * max(h, 10.0)
        else:
            assert common.rock_strength_kpa is not None
            strength_kpa = min(common.rock_strength_kpa, 25000)
            c0_mn_m3 = 300 + (strength_kpa - 1000) * (15000 - 300) / 24000
            c0_kn_m3 = c0_mn_m3 * 1000
        rotational_stiffness = c0_kn_m3 * inertia
        if (
            common.pile_tip_condition is PileTipCondition.SOIL
            and alpha_h >= 2.5 - 1e-12
        ) or (
            common.pile_tip_condition is PileTipCondition.ROCK_SURFACE
            and alpha_h >= 3.5 - 1e-12
        ):
            rotational_stiffness = 0.0
        bottom_rows = [
            transfer[3],
            [transfer[2][j] + rotational_stiffness * transfer[1][j] for j in range(4)],
        ]

    # State vector is [horizontal displacement, rotation, moment, shear].
    if common.top_constraint is PileTopConstraint.FREE:
        unknown_columns = (0, 1)
        known = [0.0, 0.0, 0.0, 1.0]
    else:
        unknown_columns = (0, 2)
        known = [0.0, 0.0, 0.0, 1.0]
    rhs = [-sum(row[j] * known[j] for j in range(4)) for row in bottom_rows]
    a, b = bottom_rows[0][unknown_columns[0]], bottom_rows[0][unknown_columns[1]]
    c, d = bottom_rows[1][unknown_columns[0]], bottom_rows[1][unknown_columns[1]]
    determinant = a * d - b * c
    if abs(determinant) < 1e-18:
        raise InputValidationError(["附录C有限长度桩方程组接近奇异，无法可靠求解"])
    first = (rhs[0] * d - b * rhs[1]) / determinant
    second = (a * rhs[1] - rhs[0] * c) / determinant
    top_state = known.copy()
    top_state[unknown_columns[0]] = first
    top_state[unknown_columns[1]] = second
    if h0 > 0:
        free_segment = _beam_transfer_matrix(h0, h0, ei, m_kn_m4 * b0)
        ground_state = [sum(free_segment[i][j] * top_state[j] for j in range(4)) for i in range(4)]
    else:
        ground_state = top_state
    compliance = abs(ground_state[0])
    if compliance <= 0 or not math.isfinite(compliance):
        raise InputValidationError(["附录C未求得有效的地面处水平位移"])
    kh = math.inf if math.isinf(rotational_stiffness) else rotational_stiffness / (alpha * ei)
    return compliance, {
        "附录C桩端条件": common.pile_tip_condition.value,
        "桩底竖向抗力系数 C0 (kN/m³)": c0_kn_m3,
        "附录C桩端约束系数 Kh": kh,
        "单位水平力地面处弯矩 M0 (kN·m/kN)": abs(ground_state[2]),
    }


def _beam_transfer_matrix(total_length: float, ground_offset: float, ei: float, mb: float) -> list[list[float]]:
    """RK4 integration of EI*x'''' + m*b*z*x = 0."""

    steps = max(400, int(total_length * 500))
    dz = total_length / steps
    matrix = [[float(i == j) for j in range(4)] for i in range(4)]

    def system(z: float) -> list[list[float]]:
        soil_depth = max(0.0, z - ground_offset)
        return [[0, 1, 0, 0], [0, 0, 1 / ei, 0], [0, 0, 0, 1], [-mb * soil_depth, 0, 0, 0]]

    def multiply(left, right):
        return [[sum(left[i][k] * right[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

    def combine(left, right, factor=1.0):
        return [[left[i][j] + factor * right[i][j] for j in range(4)] for i in range(4)]

    for index in range(steps):
        z = index * dz
        k1 = multiply(system(z), matrix)
        k2 = multiply(system(z + dz / 2), combine(matrix, k1, dz / 2))
        k3 = multiply(system(z + dz / 2), combine(matrix, k2, dz / 2))
        k4 = multiply(system(z + dz), combine(matrix, k3, dz))
        for i in range(4):
            for j in range(4):
                matrix[i][j] += dz * (k1[i][j] + 2 * k2[i][j] + 2 * k3[i][j] + k4[i][j]) / 6
    return matrix


def horizontal_capacity_from_nu(alpha: float, ei: float, displacement_m: float, nu_x: float) -> float:
    return 0.75 * alpha**3 * ei * displacement_m / nu_x


def interpolate_nu_x(constraint: PileTopConstraint, alpha_h: float) -> float:
    if alpha_h < 2.4 - 1e-9:
        raise InputValidationError(["换算埋深αh小于2.4，超出JGJ 94表5.7.2适用范围"])
    x = min(alpha_h, 4.0)
    table = NU_X_TABLE[constraint]
    keys = sorted(table)
    for key in keys:
        if math.isclose(x, key, abs_tol=1e-12):
            return table[key]
    for left, right in zip(keys, keys[1:]):
        if left < x < right:
            ratio = (x - left) / (right - left)
            return table[left] + ratio * (table[right] - table[left])
    return table[keys[-1]]


def _stability_capacity(data: MicropileInput) -> tuple[float, dict[str, float | str]]:
    if data.loads.horizontal_kn == 0:
        return math.inf, {"整体稳定说明": "水平力为0，无需验算"}
    common = data.common
    h = common.embedment_m
    eta = common.above_ground_height_m / h
    segments = list(_embedded_segments(data.soils, h))
    gamma = sum(layer.unit_weight_kn_m3 * length for layer, length in segments) / h
    beta = sum(layer.beta_deg * length for layer, length in segments) / h
    xi = (
        common.custom_xi
        if common.stability_soil_type is StabilitySoilType.CUSTOM
        else XI_DEFAULTS[common.stability_soil_type]
    )
    assert xi is not None
    theta = solve_theta(eta)
    mu_cm = 3 / (1 - 2 * theta**3)
    beta_rad = math.radians(beta)
    m_value = gamma * math.tan(math.radians(45) + beta_rad / 2) ** 2
    k0 = 1 + (2 * h / (3 * common.diameter_m)) * xi * math.cos(
        math.radians(45) + beta_rad / 2
    ) * math.tan(beta_rad)
    b0 = common.diameter_m * k0
    capacity = m_value * b0 * h**2 / (eta * mu_cm)
    return capacity, {
        "加权平均重度 γs (kN/m³)": gamma,
        "加权等代内摩擦角 β (°)": beta,
        "水平力高度比 η": eta,
        "土的侧压力系数 ξ（表8.3.15-3）": xi,
        "压力扩散角参数 θ": theta,
        "接触面间摩阻系数 μcm": mu_cm,
        "土压力参数 m (kN/m³)": m_value,
        "空间增大系数 K0": k0,
        "整体稳定计算宽度 b0 (m)": b0,
        "整体稳定水平抗力 RH (kN)": capacity,
    }


def solve_theta(eta: float) -> float:
    if eta <= 0:
        raise InputValidationError(["水平力高度比η必须大于0"])

    def polynomial(theta: float) -> float:
        return theta**3 + 1.5 * eta * theta**2 - 0.75 * eta - 0.5

    low, high = 0.0, 1.0
    for _ in range(100):
        mid = (low + high) / 2
        if polynomial(mid) > 0:
            high = mid
        else:
            low = mid
    result = (low + high) / 2
    if not 0 < result < 1:
        raise InputValidationError(["式8.3.15-9未求得0～1之间的物理解"])
    return result


def _check_horizontal_m_range(data: MicropileInput, warnings: list[str]) -> None:
    limits = HORIZONTAL_SOIL_CLASSES[data.common.horizontal_soil_class][data.pile_type]
    if limits is None:
        warnings.append("所选水平土类别在JGJ 94表5.7.5中无该桩型m值，请核对采用值。")
        return
    value = data.common.horizontal_m_mn_m4
    if not limits[0] <= value <= limits[1]:
        warnings.append(
            f"采用的m={value:g} MN/m⁴超出所选土类建议范围{limits[0]:g}～{limits[1]:g} MN/m⁴。"
        )
