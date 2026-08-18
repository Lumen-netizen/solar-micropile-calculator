from __future__ import annotations

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micropile_app.calculations import (  # noqa: E402
    _appendix_c_ground_compliance,
    _grouted_ei,
    calculate,
    effective_circumference,
    horizontal_capacity_from_nu,
    interpolate_nu_x,
    micro_short_pile_scope_exceedances,
    solve_theta,
)
from micropile_app.models import (  # noqa: E402
    CommonPileInput,
    GroutedSection,
    HelicalSection,
    HORIZONTAL_SOIL_CLASSES,
    InputValidationError,
    LoadInput,
    MicropileInput,
    PileTopConstraint,
    PileTipCondition,
    PileType,
    SoilLayer,
    SoilResistanceType,
    StabilitySoilType,
)
from micropile_app.symbols import SYMBOLS  # noqa: E402


def sample_grouted() -> MicropileInput:
    soils = (
        SoilLayer("耕植土", 0.7, 0.8, 0, 0, 0, 0),
        SoilLayer("粉质黏土", 0.7, 2.7, 16, 30, 40, 500),
    )
    common = CommonPileInput(
        diameter_m=0.3,
        embedment_m=3.5,
        above_ground_height_m=2.0,
        top_constraint=PileTopConstraint.FREE,
        allowable_displacement_mm=10,
        width_reduction_factor=1.0,
        horizontal_m_mn_m4=30,
        horizontal_soil_class=list(HORIZONTAL_SOIL_CLASSES)[2],
        stability_soil_type=StabilitySoilType.SILTY,
    )
    return MicropileInput(
        pile_type=PileType.GROUTED,
        loads=LoadInput(25, 10, 12),
        common=common,
        soils=soils,
        grouted=GroutedSection(30000, 200000, 0.0065, 0.05),
    )


def sample_helical(depths: tuple[float, ...] = (2.5, 3.4)) -> MicropileInput:
    base = sample_grouted()
    return MicropileInput(
        pile_type=PileType.HELICAL,
        loads=base.loads,
        common=replace(base.common, diameter_m=0.089, horizontal_m_mn_m4=8),
        soils=base.soils,
        helical=HelicalSection(0.006, 206000, 0.30, depths),
    )


class CalculationTests(unittest.TestCase):
    def test_normative_symbol_catalog_preserves_subscripts(self) -> None:
        self.assertEqual(SYMBOLS["N_MK"].plain, "N_Mk")
        self.assertEqual(SYMBOLS["H_MIK"].plain, "H_Mik")
        self.assertEqual(SYMBOLS["R_H"].runs, (("R", False), ("H", True)))
        self.assertEqual(SYMBOLS["K_MW"].markup, "K{Mw}")
        self.assertNotIn("H_I", SYMBOLS)

    def test_excel_grouted_reference(self) -> None:
        result = calculate(sample_grouted())
        self.assertAlmostEqual(result.intermediates["竖向总极限侧阻力 Qsk (kN)"], 101.787602, places=5)
        self.assertAlmostEqual(result.intermediates["抗压极限承载力 Quk (kN)"], 137.130519, places=5)
        self.assertAlmostEqual(result.checks["stability"].capacity_kn, 16.354070, places=5)
        self.assertAlmostEqual(result.checks["horizontal"].capacity_kn, 17.218646, places=5)
        self.assertTrue(all(check.passed for check in result.checks.values()))

    def test_excel_manual_nu_horizontal_reference(self) -> None:
        result = calculate(sample_grouted())
        alpha = result.intermediates["水平变形系数 α (1/m)"]
        ei = result.intermediates["桩身抗弯刚度 EI (kN·m²)"]
        self.assertAlmostEqual(horizontal_capacity_from_nu(alpha, ei, 0.01, 3.034), 37.675, places=3)

    def test_nu_interpolation_and_cap(self) -> None:
        self.assertAlmostEqual(interpolate_nu_x(PileTopConstraint.FREE, 2.7), 3.034)
        self.assertEqual(interpolate_nu_x(PileTopConstraint.FREE, 8), 2.441)
        with self.assertRaises(InputValidationError):
            interpolate_nu_x(PileTopConstraint.FREE, 2.39)

    def test_theta_physical_root(self) -> None:
        self.assertAlmostEqual(solve_theta(2 / 3.5), 0.758188, places=5)

    def test_effective_circumference_spacing_regions(self) -> None:
        d, D = 0.1, 0.3
        self.assertAlmostEqual(effective_circumference(2.2, d, D, (2.0, 2.8), "compression"), math.pi * D)
        self.assertAlmostEqual(effective_circumference(2.6, d, D, (2.0, 3.05), "compression"), math.pi * D)
        self.assertEqual(effective_circumference(3.0, d, D, (2.0, 3.05), "compression"), 0.0)
        self.assertAlmostEqual(effective_circumference(3.0, d, D, (2.0, 3.5), "compression"), math.pi * d)
        self.assertAlmostEqual(effective_circumference(3.3, d, D, (2.0, 3.5), "uplift"), math.pi * D)

    def test_single_and_multiple_blades_calculate(self) -> None:
        single = calculate(sample_helical())
        multiple = calculate(sample_helical((2.0, 2.8, 3.4)))
        self.assertGreater(single.checks["compression"].capacity_kn, 0)
        self.assertGreater(multiple.checks["uplift"].capacity_kn, 0)
        self.assertIn("叶片净投影面积 AD (m²)", multiple.intermediates)

    def test_blade_on_layer_interface_and_zero_tip(self) -> None:
        base = sample_helical((1.0, 2.0))
        soils = (
            SoilLayer("上层砂土", 0.5, 2.0, 18, 25, 30, 0),
            SoilLayer("下层黏土", 0.7, 1.5, 17, 20, 45, 0),
        )
        result = calculate(replace(base, soils=soils))
        self.assertEqual(result.intermediates["叶片端阻力 (kN)"], 0)
        self.assertGreater(result.checks["compression"].capacity_kn, 0)
        self.assertEqual(result.checks["compression"].controlling_layer, "上层砂土")
        self.assertIn(result.checks["uplift"].controlling_layer, {"上层砂土", "下层黏土"})

    def test_pile_type_clauses_and_helical_bearing_layer(self) -> None:
        grouted = calculate(sample_grouted())
        helical = calculate(sample_helical())
        self.assertIn("5.3.7", grouted.checks["compression"].clause)
        self.assertIn("5.3.8", grouted.checks["uplift"].clause)
        self.assertIn("5.3.9", helical.checks["compression"].clause)
        self.assertIn("5.3.10", helical.checks["uplift"].clause)
        self.assertNotIn("5.3.7", helical.checks["compression"].clause)
        self.assertEqual(helical.checks["compression"].controlling_layer, "粉质黏土")

    def test_result_has_report_serialization_boundary(self) -> None:
        payload = calculate(replace(sample_grouted(), project_name="示例光伏项目")).to_dict()
        self.assertEqual(payload["pile_type"], PileType.GROUTED.value)
        self.assertEqual(payload["normalized_input"]["project_name"], "示例光伏项目")
        self.assertIn("checks", payload)
        self.assertIn("intermediates", payload)
        self.assertNotIn("抗压控制土层", payload["intermediates"])
        self.assertNotIn("抗拔控制土层", payload["intermediates"])

    def test_layer_uplift_factor_controls_lambda(self) -> None:
        base = sample_grouted()
        cohesive = calculate(base).checks["uplift"].capacity_kn
        sand_soils = tuple(replace(layer, uplift_factor=0.5) for layer in base.soils)
        sand_input = replace(base, soils=sand_soils)
        sand = calculate(sand_input).checks["uplift"].capacity_kn
        self.assertAlmostEqual(sand / cohesive, 0.5 / 0.7)

    def test_optional_grouted_pile_self_weight_reduces_uplift_demand(self) -> None:
        base = sample_grouted()
        result = calculate(replace(base, loads=replace(base.loads, consider_pile_self_weight=True)))
        expected_volume = math.pi * base.common.diameter_m**2 / 4 * (
            base.common.above_ground_height_m + base.common.embedment_m
        )
        expected_weight = expected_volume * 25.0
        self.assertAlmostEqual(result.intermediates["计算单桩自重 Gp (kN)"], expected_weight)
        self.assertAlmostEqual(result.intermediates["抗拔验算采用单桩自重 Gp (kN)"], expected_weight)
        self.assertAlmostEqual(result.checks["uplift"].demand_kn, max(0.0, base.loads.uplift_kn - expected_weight))

    def test_optional_helical_pile_self_weight_uses_pipe_only(self) -> None:
        base = sample_helical()
        result = calculate(replace(base, loads=replace(base.loads, consider_pile_self_weight=True)))
        inner_diameter = base.common.diameter_m - 2 * base.helical.wall_thickness_m
        expected_volume = math.pi * (base.common.diameter_m**2 - inner_diameter**2) / 4 * (
            base.common.above_ground_height_m + base.common.embedment_m
        )
        self.assertAlmostEqual(result.intermediates["计算单桩自重 Gp (kN)"], expected_volume * 78.0)
        self.assertIn("忽略螺旋叶片重量", result.intermediates["桩自重计算说明"])

    def test_default_uplift_check_still_adopts_zero_self_weight(self) -> None:
        base = sample_grouted()
        result = calculate(base)
        self.assertEqual(result.intermediates["抗拔验算采用单桩自重 Gp (kN)"], 0.0)
        self.assertEqual(result.checks["uplift"].demand_kn, base.loads.uplift_kn)

    def test_soil_profile_may_extend_below_pile_tip(self) -> None:
        base = sample_grouted()
        reference = calculate(base)
        deeper_soils = base.soils + (SoilLayer("桩尖以下土层", 0.5, 3.0, 19, 35, 80, 900),)
        result = calculate(replace(base, soils=deeper_soils))
        self.assertAlmostEqual(result.checks["compression"].capacity_kn, reference.checks["compression"].capacity_kn)
        self.assertAlmostEqual(result.checks["uplift"].capacity_kn, reference.checks["uplift"].capacity_kn)
        self.assertAlmostEqual(result.checks["stability"].capacity_kn, reference.checks["stability"].capacity_kn)
        self.assertEqual(result.checks["compression"].controlling_layer, "粉质黏土")

    def test_definition_scope_exceedance_does_not_block_calculation(self) -> None:
        base = sample_grouted()
        long_soils = (replace(base.soils[1], thickness_m=7.3),)
        long_pile = replace(
            base,
            common=replace(base.common, diameter_m=0.35, embedment_m=7.3, above_ground_height_m=2.7),
            soils=long_soils,
        )
        result = calculate(long_pile)
        self.assertEqual(result.normalized_input.common.embedment_m, 7.3)
        messages = micro_short_pile_scope_exceedances(long_pile)
        self.assertEqual(len(messages), 2)
        self.assertIn("350 mm", messages[0])
        self.assertIn("7.3 m", messages[1])
        self.assertEqual(micro_short_pile_scope_exceedances(base), [])

    def test_zero_horizontal_force_skips_two_checks(self) -> None:
        base = sample_grouted()
        result = calculate(replace(base, loads=LoadInput(25, 10, 0), common=replace(base.common, above_ground_height_m=0)))
        self.assertTrue(math.isinf(result.checks["horizontal"].capacity_kn))
        self.assertTrue(math.isinf(result.checks["stability"].capacity_kn))

    def test_utilization_exactly_one_passes(self) -> None:
        base = sample_grouted()
        capacity = calculate(base).checks["compression"].capacity_kn
        result = calculate(replace(base, loads=replace(base.loads, compression_kn=capacity)))
        self.assertEqual(result.checks["compression"].utilization, 1.0)
        self.assertTrue(result.checks["compression"].passed)

    def test_invalid_inputs_are_blocked(self) -> None:
        base = sample_grouted()
        cases = [
            replace(base, grouted=replace(base.grouted, reinforcement_ratio=0.006)),
            replace(base, grouted=replace(base.grouted, cover_m=0.034)),
            replace(base, soils=(replace(base.soils[0], thickness_m=0.7), base.soils[1])),
        ]
        helix = sample_helical()
        cases.extend(
            [
                replace(helix, helical=replace(helix.helical, wall_thickness_m=0.05)),
                replace(helix, helical=replace(helix.helical, blade_depths_m=(3.0, 2.0, 3.5))),
            ]
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(InputValidationError):
                    calculate(case)

    def test_non_finite_numeric_inputs_are_blocked(self) -> None:
        grouted = sample_grouted()
        helical = sample_helical()
        cases = [
            ("荷载", lambda value: replace(grouted, loads=replace(grouted.loads, compression_kn=value))),
            ("桩身几何", lambda value: replace(grouted, common=replace(grouted.common, diameter_m=value))),
            ("可选土参数", lambda value: replace(grouted, common=replace(grouted.common, custom_xi=value))),
            ("土层参数", lambda value: replace(grouted, soils=(replace(grouted.soils[0], qsik_kpa=value), grouted.soils[1]))),
            ("灌注桩截面", lambda value: replace(grouted, grouted=replace(grouted.grouted, concrete_modulus_mpa=value))),
            ("螺旋桩截面", lambda value: replace(helical, helical=replace(helical.helical, blade_diameter_m=value))),
            ("叶片埋深", lambda value: replace(helical, helical=replace(helical.helical, blade_depths_m=(value, 3.4)))),
        ]
        for label, make_case in cases:
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=label, value=value):
                    with self.assertRaisesRegex(InputValidationError, "必须为有限数值"):
                        calculate(make_case(value))

    def test_alpha_h_below_table_uses_appendix_c(self) -> None:
        base = sample_grouted()
        shallow_soils = (replace(base.soils[1], thickness_m=0.2),)
        common = replace(base.common, embedment_m=0.2, horizontal_m_mn_m4=2.5)
        result = calculate(replace(base, soils=shallow_soils, common=common))
        self.assertEqual(result.intermediates["水平验算方法"], "JGJ 94附录C有限长度桩m法")
        self.assertGreater(result.intermediates["标准组合水平力下地面处位移 x0k (mm)"], 0)
        self.assertGreater(result.checks["horizontal"].capacity_kn, 0)
        self.assertIn("附录C", result.checks["horizontal"].clause)

    def test_appendix_c_pile_tip_conditions(self) -> None:
        base = sample_grouted()
        soils = (replace(base.soils[1], thickness_m=1.0),)
        common = replace(base.common, embedment_m=1.0, above_ground_height_m=0.5, horizontal_m_mn_m4=2.5)
        soil = calculate(replace(base, soils=soils, common=common))
        rock = calculate(replace(base, soils=soils, common=replace(common, pile_tip_condition=PileTipCondition.ROCK_SURFACE, rock_strength_kpa=10000)))
        embedded = calculate(replace(base, soils=soils, common=replace(common, pile_tip_condition=PileTipCondition.ROCK_EMBEDDED)))
        strong_rock = calculate(replace(base, soils=soils, common=replace(common, pile_tip_condition=PileTipCondition.ROCK_SURFACE, rock_strength_kpa=30000)))
        self.assertEqual(soil.intermediates["附录C桩端条件"], PileTipCondition.SOIL.value)
        self.assertAlmostEqual(rock.intermediates["桩底竖向抗力系数 C0 (kN/m³)"], 5812500, places=3)
        self.assertAlmostEqual(strong_rock.intermediates["桩底竖向抗力系数 C0 (kN/m³)"], 15000000, places=3)
        self.assertEqual(embedded.intermediates["附录C桩端条件"], PileTipCondition.ROCK_EMBEDDED.value)
        with self.assertRaisesRegex(InputValidationError, "岩石饱和单轴抗压强度"):
            calculate(replace(base, soils=soils, common=replace(common, pile_tip_condition=PileTipCondition.ROCK_SURFACE, rock_strength_kpa=None)))

    def test_appendix_c_long_pile_matches_table_5_7_2(self) -> None:
        base = sample_grouted()
        ei, section_values = _grouted_ei(base)
        inertia = float(section_values["换算惯性矩 I0 (m⁴)"])
        diameter = base.common.diameter_m
        b0 = 0.9 * (1.5 * diameter + 0.5)
        alpha = (base.common.horizontal_m_mn_m4 * 1000 * b0 / ei) ** 0.2
        for constraint in (PileTopConstraint.FREE, PileTopConstraint.FIXED):
            for alpha_h in (2.6, 2.8, 3.0, 3.5, 4.0):
                embedment = alpha_h / alpha
                common = replace(
                    base.common,
                    embedment_m=embedment,
                    above_ground_height_m=0,
                    top_constraint=constraint,
                    pile_tip_condition=PileTipCondition.SOIL,
                )
                soils = (replace(base.soils[1], thickness_m=embedment),)
                data = replace(base, common=common, soils=soils)
                compliance, values = _appendix_c_ground_compliance(data, ei, b0, inertia)
                equivalent_nu = compliance * alpha**3 * ei
                self.assertEqual(values["附录C桩端约束系数 Kh"], 0.0)
                self.assertAlmostEqual(
                    equivalent_nu,
                    interpolate_nu_x(constraint, alpha_h),
                    delta=0.0005,
                )

    def test_appendix_c_at_alpha_h_2_4_keeps_finite_tip_constraint(self) -> None:
        base = sample_grouted()
        ei, section_values = _grouted_ei(base)
        inertia = float(section_values["换算惯性矩 I0 (m⁴)"])
        diameter = base.common.diameter_m
        b0 = 0.9 * (1.5 * diameter + 0.5)
        alpha = (base.common.horizontal_m_mn_m4 * 1000 * b0 / ei) ** 0.2
        embedment = 2.4 / alpha
        soils = (replace(base.soils[1], thickness_m=embedment),)
        expected_nu = {
            PileTopConstraint.FREE: 3.5057327405,
            PileTopConstraint.FIXED: 1.0909120434,
        }
        for constraint, expected in expected_nu.items():
            common = replace(
                base.common,
                embedment_m=embedment,
                above_ground_height_m=0,
                top_constraint=constraint,
                pile_tip_condition=PileTipCondition.SOIL,
            )
            data = replace(base, common=common, soils=soils)
            compliance, values = _appendix_c_ground_compliance(data, ei, b0, inertia)
            equivalent_nu = compliance * alpha**3 * ei
            self.assertGreater(values["附录C桩端约束系数 Kh"], 0.0)
            self.assertAlmostEqual(equivalent_nu, expected, places=7)

    def test_appendix_c_controls_ground_displacement_with_exposed_length(self) -> None:
        base = sample_grouted()
        ei, section_values = _grouted_ei(base)
        inertia = float(section_values["换算惯性矩 I0 (m⁴)"])
        diameter = base.common.diameter_m
        b0 = 0.9 * (1.5 * diameter + 0.5)
        ground_compliance, values = _appendix_c_ground_compliance(base, ei, b0, inertia)
        self.assertAlmostEqual(
            values["单位水平力地面处弯矩 M0 (kN·m/kN)"],
            base.common.above_ground_height_m,
            places=9,
        )
        result = calculate(base)
        self.assertAlmostEqual(
            result.intermediates["标准组合水平力下地面处位移 x0k (mm)"],
            ground_compliance * base.loads.horizontal_kn * 1000,
            places=9,
        )
        self.assertAlmostEqual(
            result.intermediates["标准组合水平力下地面处弯矩 M0k (kN·m)"],
            base.loads.horizontal_kn * base.common.above_ground_height_m,
            places=9,
        )


if __name__ == "__main__":
    unittest.main()
