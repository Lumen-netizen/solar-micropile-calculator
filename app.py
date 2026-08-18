from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "src"))


def _configure_tcl_paths() -> None:
    base = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
    # The project-local Python runtime makes PyInstaller exclude tkinter from
    # its module archive. The build therefore ships tkinter's source package
    # beside the executable payload and adds the extraction root explicitly.
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    candidates = (
        (base / "_tcl_data", base / "_tk_data"),
        (PROJECT_DIR / "runtime_tcl" / "tcl8.6", PROJECT_DIR / "runtime_tcl" / "tk8.6"),
    )
    for tcl_dir, tk_dir in candidates:
        if (tcl_dir / "init.tcl").exists() and (tk_dir / "tk.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            return


_configure_tcl_paths()

from micropile_app.gui import MicropileApp, create_root
from micropile_app.reporting import DocxReportGenerator
from micropile_app.version import APP_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="光伏支架微型桩规范验算")
    parser.add_argument("--smoke-test", action="store_true", help="创建界面、运行默认算例并退出")
    parser.add_argument("--version", action="version", version=f"光伏支架微型桩计算程序 V{APP_VERSION}")
    args = parser.parse_args()
    smoke_data_dir = tempfile.TemporaryDirectory() if args.smoke_test else None
    if smoke_data_dir is not None:
        os.environ["MICROPILE_APP_DATA_DIR"] = smoke_data_dir.name
    root = create_root()
    if args.smoke_test:
        root.withdraw()
        root.update_idletasks()
        app = next(child for child in root.winfo_children() if isinstance(child, MicropileApp))
        information_layout_ok = (
            [app.tabs.tab(index, "text") for index in range(app.tabs.index("end"))]
            == ["桩基本信息", "地质信息", "桩土示意图"]
            and app.vars["project_name"].get() == "光伏支架微型桩项目"
            and app.section_area.pack_slaves()[-1] is app.load_frame
            and len(app.result_pane.panes()) == 2
        )
        original_result_sash = app.result_pane.sash_coord(0)[1]
        result_sash_target = original_result_sash + 40
        app.result_pane.sash_place(0, 0, result_sash_target)
        root.update_idletasks()
        result_sash_movable = abs(app.result_pane.sash_coord(0)[1] - original_result_sash) >= 20
        app.result_pane.sash_place(0, 0, original_result_sash)
        version_display_ok = f"V{APP_VERSION}" in root.title()
        work_left, work_top, work_right, work_bottom = app.initial_work_area
        window_position_ok = (
            root.winfo_x() >= work_left
            and root.winfo_y() <= work_top + 12
            and root.winfo_x() + root.winfo_width() <= work_right
            and root.winfo_y() + root.winfo_height() <= work_bottom
        )
        first_soil = app.soil_tree.get_children()[0]
        app._begin_cell_edit(first_soil, 1)
        app._editor_value.set("0.5")
        app._commit_cell_edit()
        grouted_ok = app.calculate_action(show_errors=False)
        app._draw_schematic()
        grouted_texts = [
            app.schematic_canvas.itemcget(item, "text")
            for item in app.schematic_canvas.find_all()
            if app.schematic_canvas.type(item) == "text"
        ]
        grouted_drawing_ok = len(app.schematic_canvas.find_all()) > 8 and "桩端" in grouted_texts and "桩尖" not in grouted_texts
        second_soil = app.soil_tree.get_children()[1]
        deep_values = list(app.soil_tree.item(second_soil, "values"))
        deep_values[1] = "5"
        app.soil_tree.item(second_soil, values=deep_values)
        app._update_soil_sum()
        app._draw_schematic()
        deep_texts = [
            app.schematic_canvas.itemcget(item, "text")
            for item in app.schematic_canvas.find_all()
            if app.schematic_canvas.type(item) == "text"
        ]
        deep_profile_ok = (
            app.calculate_action(show_errors=False)
            and "h₀=0.5 m" in deep_texts
            and "hₜ=2.5 m" in deep_texts
            and not any(text.startswith("⚠") for text in deep_texts)
        )
        shallow_values = list(deep_values)
        shallow_values[1] = "0.5"
        app.soil_tree.item(second_soil, values=shallow_values)
        app._update_soil_sum()
        app._draw_schematic()
        shallow_warning_ok = any(
            app.schematic_canvas.type(item) == "text"
            and app.schematic_canvas.itemcget(item, "text").startswith("⚠")
            for item in app.schematic_canvas.find_all()
        )
        deep_values[1] = "3.5"
        app.soil_tree.item(second_soil, values=deep_values)
        app._update_soil_sum()
        app.vars["pile_type"].set("钢螺旋桩")
        app._switch_pile_type()
        helical_defaults_ok = all(
            app.vars[key].get() == value
            for key, value in {
                "diameter_mm": "76", "embedment": "1.5", "height": "0.2",
                "wall_mm": "4", "blade_diameter_mm": "176", "blade_depths": "0.5, 1.3",
            }.items()
        ) and app.blade_depths_entry.master.master is app.helical_fields
        app.vars["embedment"].set("3.5")
        app.vars["height"].set("2.0")
        helical_ok = app.calculate_action(show_errors=False)
        app._draw_schematic()
        helical_texts = [
            app.schematic_canvas.itemcget(item, "text")
            for item in app.schematic_canvas.find_all()
            if app.schematic_canvas.type(item) == "text"
        ]
        helical_drawing_ok = (
            bool(app.schematic_canvas.find_all())
            and "桩尖" in helical_texts
            and "桩端" not in helical_texts
            and "总体结论" in app.summary_label.cget("text")
            and "最下层叶片端阻土层：粉质黏土" in app.bearing_layer_label.cget("text")
        )
        report_path = Path(smoke_data_dir.name) / "packaged_smoke_report.docx"
        if helical_ok and app._last_result is not None:
            DocxReportGenerator().generate(app._last_result, report_path)
        report_ok = (
            report_path.exists()
            and report_path.stat().st_size > 10_000
            and zipfile.is_zipfile(report_path)
        )
        app.vars["project_name"].set("项目保存恢复测试")
        saved_state = app._project_state()
        app.vars["project_name"].set("已修改")
        app._apply_project_state(saved_state)
        project_restore_ok = app.vars["project_name"].get() == "项目保存恢复测试"
        app.vars["pile_tip_condition"].set("桩端支承于基岩表面")
        app._switch_tip_condition()
        rock_input_ok = str(app.rock_strength_entry.cget("state")) == "normal"
        app.vars["pile_tip_condition"].set("桩端位于非岩石土层")
        app._switch_tip_condition()
        rock_input_ok = rock_input_ok and str(app.rock_strength_entry.cget("state")) == "disabled"
        horizontal_layout_ok = (
            app.tip_condition_combo.master is app.horizontal_frame
            and app.rock_strength_entry.master.master is app.horizontal_frame
            and not hasattr(app, "short_pile_frame")
        )
        ok = all((grouted_ok, helical_ok, grouted_drawing_ok, helical_drawing_ok, deep_profile_ok, shallow_warning_ok, helical_defaults_ok, information_layout_ok, result_sash_movable, version_display_ok, window_position_ok, project_restore_ok, rock_input_ok, horizontal_layout_ok, report_ok))
        root.update_idletasks()
        root.update()
        app.close_action()
        cache_path = Path(smoke_data_dir.name) / "last_session.json"
        cache_ok = cache_path.exists()
        restored_root = create_root()
        restored_root.withdraw()
        restored_root.update_idletasks()
        restored_app = next(child for child in restored_root.winfo_children() if isinstance(child, MicropileApp))
        auto_restore_ok = (
            restored_app.vars["project_name"].get() == "项目保存恢复测试"
            and restored_app.vars["pile_type"].get() == "钢螺旋桩"
            and restored_app.vars["embedment"].get() == "3.5"
        )
        restored_app.restore_defaults_action()
        restore_defaults_ok = (
            restored_app.vars["project_name"].get() == "光伏支架微型桩项目"
            and restored_app.vars["pile_type"].get() == "微型灌注桩"
            and restored_app.vars["diameter_mm"].get() == "250"
            and restored_app.vars["embedment"].get() == "2.5"
            and restored_app.vars["height"].get() == "0.5"
            and restored_app.vars["blade_depths"].get() == "0.5, 1.3"
        )
        restored_root.update_idletasks()
        restored_root.update()
        restored_app.close_action()
        cache_path.write_text("{损坏缓存", encoding="utf-8")
        fallback_root = create_root()
        fallback_root.withdraw()
        fallback_root.update_idletasks()
        fallback_app = next(child for child in fallback_root.winfo_children() if isinstance(child, MicropileApp))
        corrupt_fallback_ok = (
            fallback_app.vars["project_name"].get() == "光伏支架微型桩项目"
            and fallback_app.vars["diameter_mm"].get() == "250"
        )
        fallback_root.update_idletasks()
        fallback_root.update()
        fallback_app.close_action()
        ok = ok and cache_ok and auto_restore_ok and restore_defaults_ok and corrupt_fallback_ok
        smoke_data_dir.cleanup()
        print("GUI_SMOKE_OK" if ok else "GUI_SMOKE_FAILED")
        return 0 if ok else 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
