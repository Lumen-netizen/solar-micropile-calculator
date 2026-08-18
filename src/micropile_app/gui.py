from __future__ import annotations

import math
import re
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .calculations import calculate, micro_short_pile_scope_exceedances
from .models import (
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
    StabilitySoilType,
)
from .symbols import SYMBOLS
from .project_io import (
    ProjectDataError,
    build_project_state,
    last_session_path,
    load_project_state,
    save_project_state,
)
from .reporting import DocxReportGenerator
from .version import APP_VERSION

UPLIFT_FACTOR_OPTIONS = ("岩石：0.8", "砂土：0.5", "黏性土或粉土：0.7")
PILE_GEOMETRY_KEYS = ("diameter_mm", "embedment", "height")
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')


def _resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative_path


def _set_window_icon(root: tk.Tk) -> None:
    png_path = _resource_path("assets/micropile_app_icon.png")
    ico_path = _resource_path("assets/micropile_app_icon.ico")
    if sys.platform == "win32":
        try:
            root.iconbitmap(str(ico_path))
            return
        except tk.TclError:
            pass
    try:
        icon_image = tk.PhotoImage(file=str(png_path))
        root.iconphoto(True, icon_image)
        root._micropile_icon_image = icon_image
    except tk.TclError:
        pass


def _safe_filename_stem(value: str, fallback: str) -> str:
    return INVALID_FILENAME_CHARS.sub("_", value.strip()).strip(" .") or fallback


def _screen_work_area(root: tk.Tk) -> tuple[int, int, int, int]:
    """Return the usable desktop area, excluding the Windows taskbar."""

    if sys.platform == "win32":
        try:
            import ctypes

            class Rect(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            rect = Rect()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class RichFormulaLabel(ttk.Frame):
    """Label with real, smaller subscripts marked as ``{subscript}``."""

    def __init__(self, master: tk.Widget, text: str, foreground: str | None = None, font_size: int = 9) -> None:
        super().__init__(master)
        column = 0
        for chunk in filter(None, re.split(r"(\{[^{}]+\})", text)):
            is_subscript = chunk.startswith("{") and chunk.endswith("}")
            value = chunk[1:-1] if is_subscript else chunk
            label = ttk.Label(
                self,
                text=value,
                foreground=foreground,
                font=("Microsoft YaHei UI", max(7, font_size - 2) if is_subscript else font_size),
            )
            label.grid(row=0, column=column, sticky="s", pady=(5, 0) if is_subscript else (0, 1))
            column += 1

PARAMETER_TOOLTIPS = {
    "project_name": "项目名称\n用于标识本次计算项目，并随规范化输入保存；后续生成计算书时作为计算书项目名称。",
    "pile_type": "桩型\n选择微型灌注桩或钢螺旋桩，决定竖向承载力和截面刚度计算模型。\n依据：NB/T 10115-2018 第8.3.2条；GB 51101-2016 第5.3节。",
    "diameter_mm": "桩身外径 d，单位mm\n灌注桩取桩径，钢螺旋桩取钢管外径；用于竖向侧阻、截面刚度、水平计算宽度及整体稳定。d>300mm时继续计算，并提示超出GB 51101微型短桩定义范围。\n依据：NB/T 10115-2018 第8.3.5、8.3.15条；GB 51101-2016 第2.1.7、5.3.9～5.3.11条。",
    "embedment": "地下计算埋深 h_t，单位m\n微型灌注桩从设计地面量至桩端，钢螺旋桩量至桩尖；本App以h_t作为入土桩长判断5m定义限值。h_t>5m时继续计算并提示。\n依据：GB 51101-2016 第2.1.7条；NB/T 10115-2018 图8.3.15及式8.3.15-2。",
    "height": "桩高出地面的高度 h_0，单位m\n从设计地面量至桩顶水平力作用点；水平验算中用于将桩顶水平力传递为地面处水平力和弯矩，整体稳定验算中用于η=h_0/h_t。\n依据：NB/T 10115-2018 图8.3.15及式8.3.15-3；JGJ 94-2008表C.0.3-1。",
    "constraint": "桩顶约束\n选择铰接/自由或固接，程序据此设置附录C有限长度桩m法的桩顶边界条件。\n依据：JGJ 94-2008第5.7.2条及附录C。",
    "width_factor": "小直径计算宽度折减系数\n仅在桩径d<300mm时乘入水平承载力计算宽度b_0；默认1.0表示未折减，应由设计人员结合工程条件确认。\n依据：GB 51101-2016 第5.3.11条。",
    "ec": "混凝土弹性模量 E_c，单位MPa\n用于微型灌注桩换算截面抗弯刚度EI，仅参与水平位移分析。",
    "es": "钢筋弹性模量 E_s，单位MPa\n用于计算钢筋与混凝土弹模比α_E并换算EI，仅参与水平位移分析。",
    "rho_percent": "现有纵向配筋率ρ_g，单位%\n用于换算灌注桩截面刚度EI；本App不进行配筋设计。小于0.65%时停止位移控制验算。\n依据：NB/T 10115-2018 第8.3.8条。",
    "cover_mm": "保护层厚度 c，单位mm\n用于计算扣除保护层后的有效直径d_0并换算灌注桩EI；不应小于35mm，且应小于桩半径。\n依据：GB 51101-2016第5.4.8条。",
    "wall_mm": "钢管壁厚 t，单位mm\n与钢管外径共同计算空心圆管惯性矩I；必须小于外径的一半。叶片不计入水平抗弯刚度。",
    "steel_e": "钢材弹性模量 E，单位MPa\n用于钢螺旋桩抗弯刚度EI=E·I，仅参与水平位移分析。",
    "blade_diameter_mm": "统一叶片直径 D，单位mm\n所有叶片采用相同直径，D必须大于钢管外径；用于叶片净面积和有效计算周长。\n依据：GB 51101-2016 第5.3.9、5.3.10条。",
    "blade_depths": "各叶片埋深，单位m\n从设计地面向下量取，以逗号分隔并严格递增；通常2～3片，最下层叶片埋深必须小于ht。\n依据：GB 51101-2016 表5.3.9、表5.3.10。",
    "compression": "桩顶压力 N_Mk，单位kN\n输入荷载效应标准组合下的单桩桩顶压力包络值，用于N_Mk≤R验算。\n依据：NB/T 10115-2018 第8.3.3条。",
    "uplift": "桩顶拔力 T_k，单位kN\n输入标准组合下的单桩桩顶拔力绝对值；极限抗拔力采用T_uk。是否扣除桩自重由下方复选框控制。\n依据：GB 51101-2016 第5.3.5、5.3.8、5.3.10条。",
    "consider_self_weight": "抗拔验算考虑桩自重 G_p\n默认不勾选，此时保守取G_p=0。勾选后计算桩自重（钢螺旋桩忽略叶片重量）。\n存在地下水影响时，本App不计算浮重度，应保持不勾选并取G_p=0。\n依据：GB 51101-2016 式（5.3.5-2）。",
    "horizontal": "桩顶水平力 H_Mik，单位kN\n用于单桩水平承载力和整体稳定验算；本App中统一采用符号H_Mik。\n依据：NB/T 10115-2018 第8.3.7、8.3.15条。",
    "soil_class": "JGJ 94水平计算土类\n用于显示对应桩型的m值建议范围；应按桩侧主要受力范围内土性选择。\n依据：JGJ 94-2008 表5.7.5。",
    "horizontal_m": "水平抗力系数的比例系数 m，单位MN/m⁴\n控制地基土水平抗力随深度增长的幅度，用于计算水平变形系数α；界面默认填规范范围下限。\n依据：JGJ 94-2008 第5.7.5条及表5.7.5。",
    "displacement": "地面处允许水平位移 x_0a，单位mm\n一般结构取10mm，位移敏感结构取6mm；R_Ha与x_0a成正比，6mm时承载力为10mm时的60%。\n依据：NB/T 10115-2018第8.3.8条；JGJ 94-2008第5.7.2条。",
    "pile_tip_condition": "附录C桩端条件\n按桩端位于非岩石土层、支承于基岩表面或嵌固于基岩选择，参与有限长度桩m法的桩端边界计算。\n依据：JGJ 94-2008表C.0.3-1。",
    "rock_strength": "岩石饱和单轴抗压强度标准值frk，单位kPa\n仅在桩端支承于基岩表面时使用；1000～25000 kPa按表C.0.2插值，达到或超过25000 kPa时CR取15000 MN/m³。",
    "stability_type": "土的侧压力系数 ξ\n按土类自动采用：黏性土0.72、粉质黏土或粉土0.60、砂土0.38；用于整体稳定计算宽度。\n依据：NB/T 10115-2018 表8.3.15-3及式8.3.15-8。",
    "xi": "特殊土自定义侧压力系数 ξ\n仅当规范表8.3.15-3无法覆盖实际土类时启用，应由岩土设计依据可靠资料确定正值。\n依据：NB/T 10115-2018 表8.3.15-3。",
}

class HoverTooltip:
    def __init__(self, widget: tk.Widget, text: str | Callable[[], str], delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.after_id: str | None = None
        self.window: tk.Toplevel | None = None
        self.label: tk.Label | None = None
        self.current_text = ""
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Motion>", self._motion, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        setattr(widget, "_hover_tooltip", self)

    def _resolve_text(self) -> str:
        return self.text() if callable(self.text) else self.text

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        self.after_id = self.widget.after(self.delay_ms, self._show)

    def _motion(self, _event: tk.Event | None = None) -> None:
        if self.window is None:
            return
        text = self._resolve_text()
        if text != self.current_text:
            self._render_text(text)

    def _show(self) -> None:
        self.after_id = None
        text = self._resolve_text()
        if not text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.label = tk.Label(
            self.window,
            justify="left",
            text=text,
            background="#fffbe6",
            foreground="#263238",
            relief="solid",
            borderwidth=1,
            padx=9,
            pady=7,
            wraplength=500,
            font=("Microsoft YaHei UI", 9),
        )
        self.label.pack()
        self.current_text = text
        self.window.update_idletasks()
        x = self.widget.winfo_pointerx() + 14
        y = self.widget.winfo_pointery() + 18
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = min(x, self.widget.winfo_screenwidth() - width - 8)
        y = min(y, self.widget.winfo_screenheight() - height - 40)
        self.window.geometry(f"+{max(4, x)}+{max(4, y)}")

    def _render_text(self, text: str) -> None:
        if not text:
            self._hide()
            return
        self.current_text = text
        if self.label is not None:
            self.label.configure(text=text)

    def _cancel(self) -> None:
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self.window is not None:
            self.window.destroy()
        self.window = None
        self.label = None
        self.current_text = ""


class MicropileApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=10)
        self.master = master
        self.pack(fill="both", expand=True)
        self.vars: dict[str, tk.StringVar] = {}
        self._cell_editor: ttk.Entry | ttk.Combobox | None = None
        self._editing_item: str | None = None
        self._editing_column = 0
        self._editor_value = tk.StringVar()
        self._last_result = None
        self._geo_sash_initialized = False
        self._suspend_dirty_tracking = True
        self._make_vars()
        self._pile_geometry_values = {
            PileType.GROUTED.value: {"diameter_mm": "250", "embedment": "2.5", "height": "0.5"},
            PileType.HELICAL.value: {"diameter_mm": "76", "embedment": "1.5", "height": "0.2"},
        }
        self._active_pile_type = self.vars["pile_type"].get()
        self._build()
        self._load_default_soils()
        self._switch_pile_type()
        self._switch_xi()
        self._switch_tip_condition()
        self._default_project_state = self._project_state()
        self._restore_last_session_on_startup()
        self._install_schematic_updates()
        self._install_dirty_tracking()
        self._suspend_dirty_tracking = False
        self.master.protocol("WM_DELETE_WINDOW", self.close_action)
        self.after_idle(self._set_initial_sashes)

    def _set_initial_sashes(self) -> None:
        main_width = self.main_pane.winfo_width()
        if main_width > 900:
            self.main_pane.sash_place(0, int(main_width * 0.58), 0)
        result_height = self.result_pane.winfo_height()
        if result_height > 480:
            self.result_pane.sash_place(0, 0, max(300, result_height - 185))
        self._set_initial_geo_sash()

    def _set_initial_geo_sash(self) -> None:
        if self._geo_sash_initialized or self.tabs.select() != str(self.tab_geo):
            return
        geo_height = self.geo_pane.winfo_height()
        if geo_height > 480:
            self.geo_pane.sash_place(0, 0, int(geo_height * 0.29))
            self._geo_sash_initialized = True

    def _on_tab_changed(self, _event=None) -> None:
        if self.tabs.select() == str(self.tab_geo):
            self.after_idle(self._set_initial_geo_sash)

    def _make_vars(self) -> None:
        defaults = {
            "project_name": "光伏支架微型桩项目",
            "pile_type": PileType.GROUTED.value,
            "compression": "25",
            "uplift": "10",
            "horizontal": "6",
            "consider_self_weight": "0",
            "height": "0.5",
            "diameter_mm": "250",
            "embedment": "2.5",
            "constraint": PileTopConstraint.FREE.value,
            "displacement": "10",
            "width_factor": "1.0",
            "soil_class": list(HORIZONTAL_SOIL_CLASSES)[2],
            "horizontal_m": "30",
            "stability_type": StabilitySoilType.SILTY.value,
            "xi": "0.60",
            "pile_tip_condition": PileTipCondition.SOIL.value,
            "rock_strength": "10000",
            "ec": "30000",
            "es": "200000",
            "rho_percent": "0.65",
            "cover_mm": "35",
            "wall_mm": "4",
            "steel_e": "206000",
            "blade_diameter_mm": "176",
            "blade_depths": "0.5, 1.3",
        }
        self.vars = {key: tk.StringVar(value=value) for key, value in defaults.items()}

    def _install_dirty_tracking(self) -> None:
        for variable in self.vars.values():
            variable.trace_add("write", lambda *_args: self._mark_inputs_dirty())

    def _mark_inputs_dirty(self) -> None:
        if self._suspend_dirty_tracking:
            return
        self._last_result = None
        if hasattr(self, "report_button"):
            self.report_button.configure(state="disabled")
        if hasattr(self, "summary_label"):
            self.summary_label.configure(text="输入已修改，请重新计算", foreground="#9a6700")

    def _project_state(self) -> dict:
        if self._cell_editor is not None:
            self._commit_cell_edit()
        self._pile_geometry_values[self._active_pile_type] = {
            key: self.vars[key].get() for key in PILE_GEOMETRY_KEYS
        }
        soils = [
            [str(value) for value in self.soil_tree.item(item, "values")]
            for item in self.soil_tree.get_children()
        ]
        return build_project_state(
            {key: variable.get() for key, variable in self.vars.items()},
            soils,
            self._pile_geometry_values,
        )

    def _apply_project_state(self, state: dict, mark_dirty: bool = True) -> None:
        variables = state["variables"]
        self._suspend_dirty_tracking = True
        try:
            geometry = state.get("pile_geometry_values", {})
            for pile_type, values in geometry.items():
                if pile_type in self._pile_geometry_values:
                    self._pile_geometry_values[pile_type].update(
                        {key: value for key, value in values.items() if key in PILE_GEOMETRY_KEYS}
                    )
            for key, value in variables.items():
                if key in self.vars:
                    self.vars[key].set(value)
            selected_type = self.vars["pile_type"].get()
            if selected_type not in self._pile_geometry_values:
                raise ProjectDataError(f"项目文件中的桩型无效：{selected_type}")
            self._active_pile_type = selected_type
            self._pile_geometry_values[selected_type] = {
                key: self.vars[key].get() for key in PILE_GEOMETRY_KEYS
            }
            self._close_cell_editor()
            for item in self.soil_tree.get_children():
                self.soil_tree.delete(item)
            for row in state["soils"]:
                self.soil_tree.insert("", "end", values=row)
            horizontal_m = variables.get("horizontal_m")
            self._switch_pile_type()
            if horizontal_m is not None:
                self.vars["horizontal_m"].set(horizontal_m)
            self._switch_xi()
            self._switch_tip_condition()
            self._update_width_warning()
            self._update_soil_sum()
            self._draw_schematic()
        finally:
            self._suspend_dirty_tracking = False
        if mark_dirty:
            self._mark_inputs_dirty()

    def save_project_action(self) -> bool:
        project_name = self.vars["project_name"].get().strip() or "微型桩项目"
        safe_name = _safe_filename_stem(project_name, "微型桩项目")
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="保存微型桩项目",
            defaultextension=".json",
            initialfile=f"{safe_name}.json",
            filetypes=(("微型桩项目文件", "*.json"), ("所有文件", "*.*")),
        )
        if not filename:
            return False
        try:
            save_project_state(self._project_state(), Path(filename))
        except (OSError, ProjectDataError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return False
        messagebox.showinfo("保存完成", f"项目参数已保存至：\n{filename}", parent=self)
        return True

    def open_project_action(self) -> bool:
        filename = filedialog.askopenfilename(
            parent=self,
            title="打开微型桩项目",
            filetypes=(("微型桩项目文件", "*.json"), ("所有文件", "*.*")),
        )
        if not filename:
            return False
        return self._load_project_path(Path(filename), "项目已打开，请点击“计算”更新结果。")

    def _restore_last_session_on_startup(self) -> bool:
        path = last_session_path()
        if not path.exists():
            return False
        try:
            self._apply_project_state(load_project_state(path), mark_dirty=False)
        except (OSError, ProjectDataError, tk.TclError):
            return False
        self._set_calculation_pending("已自动恢复上次关闭时的输入，请点击“计算”。")
        return True

    def restore_defaults_action(self) -> bool:
        self._apply_project_state(self._default_project_state, mark_dirty=False)
        self._set_calculation_pending("已恢复程序默认参数，请点击“计算”。")
        return True

    def _set_calculation_pending(self, message: str) -> None:
        self._last_result = None
        self.report_button.configure(state="disabled")
        self.summary_label.configure(text=message, foreground="#315d83")

    def _load_project_path(self, path: Path, success_message: str) -> bool:
        try:
            self._apply_project_state(load_project_state(path))
        except (OSError, ProjectDataError, tk.TclError) as exc:
            messagebox.showerror("读取失败", str(exc), parent=self)
            return False
        self.summary_label.configure(text=success_message, foreground="#315d83")
        return True

    def close_action(self) -> None:
        try:
            save_project_state(self._project_state(), last_session_path())
        except (OSError, ProjectDataError):
            pass
        self.master.destroy()

    def _build(self) -> None:
        self.master.title(f"光伏支架微型桩计算程序 V{APP_VERSION}")
        left, top, right, bottom = _screen_work_area(self.master)
        work_width, work_height = right - left, bottom - top
        width = min(1225, max(900, work_width - 32))
        height = min(840, max(650, work_height - 48))
        x = left + max(8, (work_width - width) // 2)
        y = top + 8
        self.master.geometry(f"{width}x{height}+{x}+{y}")
        self.master.minsize(min(1120, width), min(720, height))
        self.initial_work_area = (left, top, right, bottom)
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("CardTitle.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Pass.TLabel", foreground="#147d3f", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Fail.TLabel", foreground="#b42318", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Soil.Treeview", rowheight=31, font=("Microsoft YaHei UI", 9))
        style.configure("Soil.Treeview.Heading", font=("Microsoft YaHei UI", 9), padding=(4, 18))

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="光伏支架微型桩规范验算", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"V{APP_VERSION}", foreground="#5f6b7a").pack(side="left", padx=(10, 0))
        ttk.Label(header, text="NB/T 10115 · GB 51101 · JGJ 94", foreground="#5f6b7a").pack(side="left", padx=16)
        self.report_button = ttk.Button(header, text="生成计算书", command=self.generate_report_action, state="disabled")
        self.report_button.pack(side="right")
        ttk.Button(header, text="计算", command=self.calculate_action).pack(side="right", padx=(8, 4))
        ttk.Button(header, text="保存项目", command=self.save_project_action).pack(side="right", padx=4)
        ttk.Button(header, text="打开项目", command=self.open_project_action).pack(side="right", padx=4)
        ttk.Button(header, text="恢复默认", command=self.restore_defaults_action).pack(side="right", padx=4)

        self.main_pane = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashwidth=9,
            sashrelief=tk.RAISED,
            showhandle=True,
            handlesize=12,
            handlepad=90,
            opaqueresize=True,
            background="#aeb8c4",
            borderwidth=0,
        )
        self.main_pane.pack(fill="both", expand=True)
        input_panel = ttk.Frame(self.main_pane, padding=(0, 0, 8, 0))
        result_panel = ttk.Frame(self.main_pane, padding=(8, 0, 0, 0))
        self.main_pane.add(input_panel, minsize=520, stretch="always")
        self.main_pane.add(result_panel, minsize=360, stretch="always")

        self.tabs = ttk.Notebook(input_panel)
        self.tabs.pack(fill="both", expand=True)
        self.tab_pile = ttk.Frame(self.tabs, padding=12)
        self.tab_geo = ttk.Frame(self.tabs, padding=12)
        self.tab_schematic = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_pile, text="桩基本信息")
        self.tabs.add(self.tab_geo, text="地质信息")
        self.tabs.add(self.tab_schematic, text="桩土示意图")
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        self._build_pile_tab()
        self._build_geo_tab()
        self._build_schematic_tab()
        self._build_results(result_panel)

    def _row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        key: str,
        unit: str = "",
        suffix_note: str = "",
    ) -> ttk.Entry:
        label_widget: ttk.Label | RichFormulaLabel
        label_widget = RichFormulaLabel(parent, label) if "{" in label else ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=5)
        value_frame = ttk.Frame(parent)
        value_frame.grid(row=row, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=5)
        entry = ttk.Entry(value_frame, textvariable=self.vars[key], width=18)
        entry.pack(side="left")
        if unit:
            ttk.Label(value_frame, text=unit, foreground="#5f6b7a").pack(side="left", padx=(5, 0))
        if suffix_note:
            ttk.Label(value_frame, text=suffix_note, foreground="#5f6b7a").pack(side="left", padx=(6, 0))
        HoverTooltip(entry, PARAMETER_TOOLTIPS[key])
        return entry

    def _build_pile_tab(self) -> None:
        tab = self.tab_pile
        tab.columnconfigure(0, weight=1)
        self.common_fields = ttk.Frame(tab)
        self.common_fields.grid(row=0, column=0, sticky="w")
        ttk.Label(self.common_fields, text="项目名称").grid(row=0, column=0, sticky="w", pady=5)
        project_entry = ttk.Entry(self.common_fields, textvariable=self.vars["project_name"], width=36)
        project_entry.grid(row=0, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=5)
        HoverTooltip(project_entry, PARAMETER_TOOLTIPS["project_name"])
        ttk.Label(self.common_fields, text="桩型").grid(row=1, column=0, sticky="w", pady=5)
        pile_combo = ttk.Combobox(self.common_fields, textvariable=self.vars["pile_type"], values=[item.value for item in PileType], state="readonly", width=20)
        pile_combo.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)
        pile_combo.bind("<<ComboboxSelected>>", lambda _event: self._switch_pile_type())
        HoverTooltip(pile_combo, PARAMETER_TOOLTIPS["pile_type"])
        self._row(self.common_fields, 2, "桩身外径 d", "diameter_mm", "mm")
        self._row(self.common_fields, 3, f"地下计算埋深 {SYMBOLS['H_T'].markup}", "embedment", "m")
        self._row(self.common_fields, 4, f"桩高出地面的高度 {SYMBOLS['H_0'].markup}", "height", "m")
        ttk.Label(self.common_fields, text="桩顶约束").grid(row=5, column=0, sticky="w", pady=5)
        constraint_combo = ttk.Combobox(self.common_fields, textvariable=self.vars["constraint"], values=[item.value for item in PileTopConstraint], state="readonly", width=18)
        constraint_combo.grid(row=5, column=1, sticky="w", padx=(10, 0), pady=5)
        HoverTooltip(constraint_combo, PARAMETER_TOOLTIPS["constraint"])
        self._row(self.common_fields, 6, "小直径计算宽度折减系数\n（仅用于水平承载力验算）", "width_factor")
        self.width_warning = ttk.Label(tab, text="", foreground="#9a6700", wraplength=500)
        self.width_warning.grid(row=1, column=0, sticky="w", pady=(2, 8))
        self.vars["diameter_mm"].trace_add("write", lambda *_: self._update_width_warning())
        self._update_width_warning()

        self.section_area = ttk.Frame(tab)
        self.section_area.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.section_area.columnconfigure(0, weight=1)
        self.grouted_frame = ttk.LabelFrame(self.section_area, text="微型灌注桩桩截面参数", padding=10)
        self.helical_frame = ttk.LabelFrame(self.section_area, text="钢螺旋桩截面参数", padding=10)
        self._row(self.grouted_frame, 0, f"混凝土弹性模量 {SYMBOLS['E_C'].markup}", "ec", "MPa")
        self._row(self.grouted_frame, 1, f"钢筋弹性模量 {SYMBOLS['E_S'].markup}", "es", "MPa")
        self._row(self.grouted_frame, 2, f"现有配筋率 {SYMBOLS['RHO_G'].markup}", "rho_percent", "%")
        self._row(self.grouted_frame, 3, "保护层厚度 c", "cover_mm", "mm")
        ttk.Label(self.grouted_frame, text="配筋率仅用于换算 EI；本 App 不进行桩身强度和配筋验算。", foreground="#5f6b7a", wraplength=520).grid(row=4, column=0, columnspan=3, sticky="w", pady=8)
        self.helical_fields = ttk.Frame(self.helical_frame)
        self.helical_fields.grid(row=0, column=0, sticky="w")
        self.helical_fields.columnconfigure(0, minsize=151)
        self._row(self.helical_fields, 0, "钢管壁厚", "wall_mm", "mm")
        self._row(self.helical_fields, 1, "钢材弹性模量", "steel_e", "MPa")
        self._row(self.helical_fields, 2, "统一叶片直径", "blade_diameter_mm", "mm")
        self.blade_depths_entry = self._row(self.helical_fields, 3, "各叶片埋深\n（逗号分隔）", "blade_depths", "m")
        ttk.Label(
            self.helical_frame,
            text="从地面向下量取并严格递增；通常设置2～3片，最下层叶片必须位于桩尖以上（埋深小于ht）。",
            foreground="#5f6b7a",
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.load_frame = ttk.LabelFrame(self.section_area, text="荷载（标准组合包络值）", padding=10)
        self._row(self.load_frame, 0, f"桩顶压力 {SYMBOLS['N_MK'].markup}", "compression", "kN")
        self._row(self.load_frame, 1, f"桩顶拔力 {SYMBOLS['T_K'].markup}", "uplift", "kN")
        self._row(self.load_frame, 2, f"桩顶水平力 {SYMBOLS['H_MIK'].markup}", "horizontal", "kN")
        self.self_weight_check = ttk.Checkbutton(
            self.load_frame,
            text="抗拔验算考虑桩自重 Gₚ",
            variable=self.vars["consider_self_weight"],
            onvalue="1",
            offvalue="0",
        )
        self.self_weight_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(7, 2))
        HoverTooltip(self.self_weight_check, PARAMETER_TOOLTIPS["consider_self_weight"])

    def _build_geo_tab(self) -> None:
        tab = self.tab_geo
        self.geo_pane = tk.PanedWindow(
            tab,
            orient=tk.VERTICAL,
            sashwidth=9,
            sashrelief=tk.RAISED,
            showhandle=True,
            handlesize=12,
            handlepad=80,
            opaqueresize=True,
            background="#aeb8c4",
            borderwidth=0,
        )
        self.geo_pane.pack(fill="both", expand=True)
        soil_panel = ttk.Frame(self.geo_pane, padding=(0, 0, 0, 5))
        calculation_panel = ttk.Frame(self.geo_pane, padding=(0, 5, 0, 0))
        self.geo_pane.add(soil_panel, minsize=160, stretch="always")
        self.geo_pane.add(calculation_panel, minsize=300, stretch="never")
        ttk.Label(soil_panel, text="土层信息参数").pack(anchor="w", pady=(0, 5))
        columns = ("name", "thickness", "gamma", "beta", "qsi", "qpk", "lambda")
        table_frame = ttk.Frame(soil_panel)
        table_frame.pack(fill="both", expand=True)
        self.soil_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8, style="Soil.Treeview")
        labels = (
            "土层名称",
            "土层厚度 li\n(m)",
            "重度 γ\n(kN/m³)",
            "等代内摩擦角 β\n(°)",
            "桩侧极限侧阻力\n标准值 qsik (kPa)",
            "桩端极限端阻力\n标准值 qpk (kPa)",
            "抗拔系数 λ\n（土类：数值）",
        )
        widths = (95, 85, 90, 110, 130, 130, 155)
        for column, label, width in zip(columns, labels, widths):
            self.soil_tree.heading(column, text=label)
            self.soil_tree.column(column, width=width, minwidth=70, stretch=False, anchor="center")
        self.soil_tree.pack(fill="both", expand=True)
        self.soil_tree.bind("<Double-1>", self._begin_cell_edit_from_event)
        buttons = ttk.Frame(calculation_panel)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="新增土层", command=self.add_soil).pack(side="left")
        ttk.Button(buttons, text="编辑", command=self.edit_soil).pack(side="left", padx=6)
        ttk.Button(buttons, text="删除", command=self.delete_soil).pack(side="left")
        self.soil_sum_label = ttk.Label(buttons, text="")
        self.soil_sum_label.pack(side="right")
        self.bearing_layer_label = ttk.Label(calculation_panel, text="桩端持力层：—", foreground="#305c8c")
        self.bearing_layer_label.pack(anchor="w", pady=(0, 8))
        ttk.Label(
            calculation_panel,
            text="qsik、qpk按勘察报告或规范取值；灌注桩端阻取桩端所在土层qpk，螺旋桩端阻取最下层叶片所在土层qpk。",
            foreground="#5f6b7a",
            wraplength=800,
        ).pack(anchor="w", pady=(0, 8))

        horizontal = ttk.LabelFrame(calculation_panel, text="水平承载力验算参数（地面处位移控制）", padding=8)
        horizontal.pack(fill="x")
        self.horizontal_frame = horizontal
        ttk.Label(horizontal, text="JGJ 94 土类").grid(row=0, column=0, sticky="w", pady=5)
        soil_combo = ttk.Combobox(horizontal, textvariable=self.vars["soil_class"], values=list(HORIZONTAL_SOIL_CLASSES), state="readonly", width=42)
        soil_combo.grid(row=0, column=1, sticky="w", padx=(10, 5), pady=5)
        soil_combo.bind("<<ComboboxSelected>>", lambda _event: self._set_m_lower_bound())
        HoverTooltip(soil_combo, PARAMETER_TOOLTIPS["soil_class"])
        m_entry = self._row(horizontal, 1, "设计采用 m 值", "horizontal_m", "MN/m⁴")
        self.m_range_label = ttk.Label(m_entry.master, foreground="#5f6b7a")
        self.m_range_label.pack(side="left", padx=(8, 0))
        RichFormulaLabel(horizontal, f"地面处允许水平位移 {SYMBOLS['X_0A'].markup}").grid(row=2, column=0, sticky="w", pady=5)
        displacement_value = ttk.Frame(horizontal)
        displacement_value.grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=5)
        displacement_combo = ttk.Combobox(displacement_value, textvariable=self.vars["displacement"], values=("10", "6"), state="readonly", width=18)
        displacement_combo.pack(side="left")
        HoverTooltip(displacement_combo, PARAMETER_TOOLTIPS["displacement"])
        ttk.Label(displacement_value, text="mm").pack(side="left", padx=(5, 0))

        ttk.Label(horizontal, text="附录C桩端条件").grid(row=3, column=0, sticky="w", pady=5)
        tip_combo = ttk.Combobox(
            horizontal,
            textvariable=self.vars["pile_tip_condition"],
            values=[item.value for item in PileTipCondition],
            state="readonly",
            width=28,
        )
        self.tip_condition_combo = tip_combo
        tip_combo.grid(row=3, column=1, sticky="w", padx=(10, 5), pady=5)
        tip_combo.bind("<<ComboboxSelected>>", lambda _event: self._switch_tip_condition())
        HoverTooltip(tip_combo, PARAMETER_TOOLTIPS["pile_tip_condition"])
        self.rock_strength_entry = self._row(
            horizontal,
            4,
            "岩石饱和单轴抗压强度标准值 f_rk",
            "rock_strength",
            "kPa",
            "（仅用于桩端支承于基岩表面）",
        )
        horizontal.columnconfigure(1, weight=1)

        stability = ttk.LabelFrame(calculation_panel, text="整体稳定（抗倾覆）参数", padding=10)
        stability.pack(fill="x", pady=(8, 0))
        ttk.Label(stability, text="土的侧压力系数 ξ\n（NB/T 10115 表8.3.15-3）").grid(row=0, column=0, sticky="w", pady=5)
        combo = ttk.Combobox(stability, textvariable=self.vars["stability_type"], values=[item.value for item in StabilitySoilType], state="readonly", width=22)
        combo.grid(row=0, column=1, sticky="w", padx=(10, 5), pady=5)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._switch_xi())
        HoverTooltip(combo, PARAMETER_TOOLTIPS["stability_type"])
        self.xi_entry = self._row(stability, 1, "特殊土自定义侧压力系数 ξ", "xi")
        stability.columnconfigure(1, weight=1)

    def _build_results(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="结果", style="Title.TLabel").pack(anchor="w")
        self.summary_label = ttk.Label(parent, text="尚未计算", foreground="#5f6b7a", font=("Microsoft YaHei UI", 11, "bold"), wraplength=520)
        self.summary_label.pack(fill="x", pady=(6, 8))

        self.result_pane = tk.PanedWindow(
            parent,
            orient=tk.VERTICAL,
            sashwidth=9,
            sashrelief=tk.RAISED,
            showhandle=True,
            handlesize=12,
            handlepad=90,
            opaqueresize=True,
            background="#aeb8c4",
            borderwidth=0,
        )
        self.result_pane.pack(fill="both", expand=True)

        core_panel = ttk.Frame(self.result_pane)
        ttk.Label(core_panel, text="核心计算结果", style="CardTitle.TLabel").pack(anchor="w")
        self.card_frame = ttk.Frame(core_panel)
        self.card_frame.pack(fill="both", expand=True, pady=(4, 4))
        self.empty_label = ttk.Label(self.card_frame, text="输入参数后点击“计算”", foreground="#5f6b7a")
        self.empty_label.pack(anchor="w", pady=20)

        detail_panel = ttk.Frame(self.result_pane)
        ttk.Label(detail_panel, text="中间计算（可滚动查看）", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 4))
        text_frame = ttk.Frame(detail_panel)
        text_frame.pack(fill="both", expand=True)
        self.detail_text = tk.Text(text_frame, height=9, wrap="word", font=("Microsoft YaHei UI", 9), state="disabled")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=scrollbar.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.result_pane.add(core_panel, minsize=300, stretch="always")
        self.result_pane.add(detail_panel, minsize=95, stretch="always")

    def _build_schematic_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_schematic)
        toolbar.pack(fill="x", pady=(0, 5))
        ttk.Label(toolbar, text="竖向尺寸按输入比例绘制；桩身横向宽度仅作示意。", foreground="#5f6b7a").pack(side="left")
        ttk.Button(toolbar, text="刷新示意图", command=self._draw_schematic).pack(side="right")
        self.schematic_canvas = tk.Canvas(self.tab_schematic, background="#ffffff", highlightthickness=1, highlightbackground="#b8c0ca")
        self.schematic_canvas.pack(fill="both", expand=True)
        self.schematic_canvas.bind("<Configure>", lambda _event: self._draw_schematic())

    def _install_schematic_updates(self) -> None:
        for key in ("pile_type", "diameter_mm", "embedment", "height", "blade_diameter_mm", "blade_depths"):
            self.vars[key].trace_add("write", lambda *_args: self.after_idle(self._draw_schematic))
        self.vars["embedment"].trace_add("write", lambda *_args: self.after_idle(self._update_soil_sum))
        self.vars["pile_type"].trace_add("write", lambda *_args: self.after_idle(self._update_soil_sum))
        self.vars["blade_depths"].trace_add("write", lambda *_args: self.after_idle(self._update_soil_sum))
        self.tabs.bind("<<NotebookTabChanged>>", lambda _event: self.after_idle(self._draw_schematic), add="+")
        self.after_idle(self._draw_schematic)

    def _draw_schematic(self) -> None:
        if not hasattr(self, "schematic_canvas") or not self.schematic_canvas.winfo_exists():
            return
        canvas = self.schematic_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 460)
        try:
            h0 = float(self.vars["height"].get())
            ht = float(self.vars["embedment"].get())
            diameter_mm = float(self.vars["diameter_mm"].get())
            if h0 < 0 or ht <= 0 or diameter_mm <= 0:
                raise ValueError
        except ValueError:
            canvas.create_text(width / 2, height / 2, text="请输入有效的 h0、ht 和桩径后显示示意图", fill="#b42318", font=("Microsoft YaHei UI", 11))
            return

        soil_rows: list[tuple[str, float]] = []
        for item in self.soil_tree.get_children():
            values = self.soil_tree.item(item, "values")
            try:
                thickness = float(values[1])
            except (ValueError, IndexError):
                continue
            if thickness > 0:
                soil_rows.append((str(values[0]), thickness))
        soil_sum = sum(thickness for _name, thickness in soil_rows)
        below_extent = max(ht, soil_sum, 0.1)
        margin_top, margin_bottom = 42, 52
        scale = (height - margin_top - margin_bottom) / max(h0 + below_extent, 0.1)
        ground_y = margin_top + h0 * scale
        tip_y = ground_y + ht * scale
        soil_width = min(760, max(330, width - 180))
        soil_left = (width - soil_width) / 2
        soil_right = soil_left + soil_width
        pile_x = (soil_left + soil_right) / 2
        palette = ("#f3dfb3", "#d9c39a", "#e8c98d", "#c9d8ad", "#d7b89c", "#bdd4d8", "#ddd0aa")

        depth = 0.0
        for index, (name, thickness) in enumerate(soil_rows):
            y1 = ground_y + depth * scale
            y2 = ground_y + (depth + thickness) * scale
            canvas.create_rectangle(soil_left, y1, soil_right, y2, fill=palette[index % len(palette)], outline="#7e8791")
            canvas.create_text(soil_right - 12, (y1 + y2) / 2, anchor="e", text=f"{name}  {thickness:g} m", fill="#263238", font=("Microsoft YaHei UI", 10))
            canvas.create_text(soil_left + 8, y2 - 4, anchor="sw", text=f"深度 {depth + thickness:g} m", fill="#59636e", font=("Microsoft YaHei UI", 8))
            depth += thickness

        canvas.create_line(soil_left - 12, ground_y, soil_right + 12, ground_y, width=3, fill="#2f3b45")
        canvas.create_text(soil_left - 5, ground_y - 8, anchor="sw", text="设计地面", fill="#263238", font=("Microsoft YaHei UI", 10, "bold"))

        pile_type = PileType(self.vars["pile_type"].get())
        if pile_type is PileType.GROUTED:
            pile_width = max(26, min(64, diameter_mm / 6))
            canvas.create_rectangle(pile_x - pile_width / 2, margin_top, pile_x + pile_width / 2, tip_y, fill="#d8dde3", outline="#3e4a55", width=2)
            canvas.create_text(pile_x, margin_top - 12, text="微型灌注桩", fill="#263238", font=("Microsoft YaHei UI", 10, "bold"))
        else:
            shaft_width = max(10, min(24, diameter_mm / 7))
            point_height = max(14, min(25, 0.05 * (tip_y - ground_y)))
            point_base = tip_y - point_height
            canvas.create_rectangle(pile_x - shaft_width / 2, margin_top, pile_x + shaft_width / 2, point_base, fill="#8e9aa5", outline="#34404a", width=2)
            canvas.create_polygon(pile_x - shaft_width / 2, point_base, pile_x + shaft_width / 2, point_base, pile_x, tip_y, fill="#8e9aa5", outline="#34404a", width=2)
            try:
                blade_diameter = float(self.vars["blade_diameter_mm"].get())
                blade_depths = [float(part.strip()) for part in self.vars["blade_depths"].get().replace("，", ",").split(",") if part.strip()]
            except ValueError:
                blade_diameter, blade_depths = diameter_mm * 2, []
            blade_half = shaft_width * blade_diameter / diameter_mm / 2
            blade_height = max(5, min(10, blade_half * 0.32))
            for number, blade_depth in enumerate(blade_depths, start=1):
                y = ground_y + blade_depth * scale
                canvas.create_oval(
                    pile_x - blade_half, y - blade_height, pile_x + blade_half, y + blade_height,
                    fill="#ffd36a", outline="#c33a2c", width=3,
                )
                canvas.create_line(
                    pile_x - blade_half, y + blade_height * 0.55,
                    pile_x + blade_half, y - blade_height * 0.55,
                    fill="#a9271b", width=3,
                )
                canvas.create_oval(
                    pile_x - shaft_width, y - blade_height * 0.36,
                    pile_x + shaft_width, y + blade_height * 0.36,
                    fill="#c46b2d", outline="#7d231b", width=2,
                )
                canvas.create_text(pile_x + blade_half + 8, y, anchor="w", text=f"叶片{number}  {blade_depth:g} m", fill="#5b4317", font=("Microsoft YaHei UI", 9))
            canvas.create_text(pile_x, margin_top - 12, text="钢螺旋桩", fill="#263238", font=("Microsoft YaHei UI", 10, "bold"))

        dimension_x = soil_left - 42
        self._draw_dimension(canvas, dimension_x, margin_top, ground_y, "h₀", f"{h0:g} m")
        self._draw_dimension(canvas, dimension_x, ground_y, tip_y, "hₜ", f"{ht:g} m")
        canvas.create_line(pile_x - 45, tip_y, pile_x + 45, tip_y, fill="#59636e", dash=(4, 3))
        end_label = "桩端" if pile_type is PileType.GROUTED else "桩尖"
        canvas.create_text(pile_x + 50, tip_y, anchor="w", text=end_label, fill="#263238", font=("Microsoft YaHei UI", 9))

        if soil_sum < ht - 1e-6:
            canvas.create_text(
                width / 2,
                height - 18,
                text=f"⚠ 土层总厚度仅 {soil_sum:g} m，小于 ht={ht:g} m，尚缺 {ht - soil_sum:g} m，无法覆盖完整桩长",
                fill="#b42318",
                font=("Microsoft YaHei UI", 10, "bold"),
            )

    @staticmethod
    def _draw_dimension(canvas: tk.Canvas, x: float, y1: float, y2: float, symbol: str, value: str) -> None:
        canvas.create_line(x, y1, x, y2, fill="#7a5b00", width=2, arrow=tk.BOTH)
        canvas.create_line(x, y1, x + 25, y1, fill="#7a5b00")
        canvas.create_line(x, y2, x + 25, y2, fill="#7a5b00")
        canvas.create_text(
            x - 14,
            (y1 + y2) / 2,
            text=f"{symbol}={value}",
            angle=90,
            fill="#5e4700",
            font=("Microsoft YaHei UI", 9, "bold"),
        )

    def _switch_pile_type(self) -> None:
        selected_type = self.vars["pile_type"].get()
        if selected_type != self._active_pile_type:
            self._pile_geometry_values[self._active_pile_type] = {
                key: self.vars[key].get() for key in PILE_GEOMETRY_KEYS
            }
            for key, value in self._pile_geometry_values[selected_type].items():
                self.vars[key].set(value)
            self._active_pile_type = selected_type
        self.grouted_frame.pack_forget()
        self.helical_frame.pack_forget()
        self.load_frame.pack_forget()
        if self.vars["pile_type"].get() == PileType.GROUTED.value:
            self.grouted_frame.pack(fill="x")
        else:
            self.helical_frame.pack(fill="x")
        self.load_frame.pack(fill="x", pady=(8, 0))
        self._set_m_lower_bound()
        self._update_soil_sum()
        if hasattr(self, "schematic_canvas"):
            self.after_idle(self._draw_schematic)

    def _set_m_lower_bound(self) -> None:
        try:
            pile_type = PileType(self.vars["pile_type"].get())
            limits = HORIZONTAL_SOIL_CLASSES[self.vars["soil_class"].get()][pile_type]
        except (KeyError, ValueError):
            return
        if limits is None:
            self.m_range_label.configure(text="（该桩型在规范表中无建议范围，请人工核定）")
        else:
            self.vars["horizontal_m"].set(f"{limits[0]:g}")
            self.m_range_label.configure(text=f"（规范建议范围：{limits[0]:g}～{limits[1]:g} MN/m⁴；已填保守下限）")

    def _switch_xi(self) -> None:
        custom = self.vars["stability_type"].get() == StabilitySoilType.CUSTOM.value
        self.xi_entry.configure(state="normal" if custom else "disabled")

    def _switch_tip_condition(self) -> None:
        if not hasattr(self, "rock_strength_entry"):
            return
        enabled = self.vars["pile_tip_condition"].get() == PileTipCondition.ROCK_SURFACE.value
        self.rock_strength_entry.configure(state="normal" if enabled else "disabled")

    def _update_width_warning(self) -> None:
        try:
            small = float(self.vars["diameter_mm"].get()) < 300
        except ValueError:
            small = False
        self.width_warning.configure(text="⚠ 桩径小于300 mm，请确认计算宽度折减系数；默认1.0不会产生折减。" if small else "")

    def _load_default_soils(self) -> None:
        self.soil_tree.insert("", "end", values=("耕植土", "0.5", "0", "0", "0", "0", "黏性土或粉土：0.7"))
        self.soil_tree.insert("", "end", values=("粉质黏土", "3.5", "16", "30", "40", "500", "黏性土或粉土：0.7"))
        self._update_soil_sum()

    def add_soil(self) -> None:
        item = self.soil_tree.insert("", "end", values=("新土层", "1.0", "18", "20", "0", "0", "黏性土或粉土：0.7"))
        self.soil_tree.selection_set(item)
        self.soil_tree.focus(item)
        self.soil_tree.see(item)
        self._update_soil_sum()
        self._mark_inputs_dirty()
        self.after_idle(lambda: self._begin_cell_edit(item, 0))

    def edit_soil(self) -> None:
        selection = self.soil_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要编辑的土层。", parent=self)
            return
        self._begin_cell_edit(selection[0], 0)

    def delete_soil(self) -> None:
        self._close_cell_editor()
        for item in self.soil_tree.selection():
            self.soil_tree.delete(item)
        self._update_soil_sum()
        self._mark_inputs_dirty()

    def _begin_cell_edit_from_event(self, event: tk.Event) -> None:
        item = self.soil_tree.identify_row(event.y)
        column = self.soil_tree.identify_column(event.x)
        if item and column.startswith("#"):
            self._begin_cell_edit(item, int(column[1:]) - 1)

    def _begin_cell_edit(self, item: str, column_index: int) -> None:
        if self._cell_editor is not None:
            self._commit_cell_edit()
            if self._cell_editor is not None:
                return
        bbox = self.soil_tree.bbox(item, f"#{column_index + 1}")
        if not bbox:
            return
        x, y, width, height = bbox
        values = list(self.soil_tree.item(item, "values"))
        self._editing_item = item
        self._editing_column = column_index
        self._editor_value.set(str(values[column_index]))
        if column_index == 6:
            editor: ttk.Entry | ttk.Combobox = ttk.Combobox(
                self.soil_tree,
                textvariable=self._editor_value,
                values=UPLIFT_FACTOR_OPTIONS,
                state="readonly",
            )
            editor.bind("<<ComboboxSelected>>", lambda _event: self._commit_cell_edit(1))
        else:
            editor = ttk.Entry(self.soil_tree, textvariable=self._editor_value)
            editor.select_range(0, "end")
        self._cell_editor = editor
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.bind("<Return>", lambda _event: self._commit_cell_edit(1))
        editor.bind("<Tab>", lambda _event: self._commit_cell_edit(1))
        editor.bind("<Shift-Tab>", lambda _event: self._commit_cell_edit(-1))
        editor.bind("<Escape>", lambda _event: self._close_cell_editor())

    def _commit_cell_edit(self, move: int = 0) -> str:
        if self._cell_editor is None or self._editing_item is None:
            return "break"
        item = self._editing_item
        column = self._editing_column
        value = self._editor_value.get().strip()
        if column == 0 and not value:
            messagebox.showerror("输入错误", "土层名称不能为空。", parent=self)
            self._cell_editor.focus_set()
            return "break"
        if column == 6 and value not in UPLIFT_FACTOR_OPTIONS:
            messagebox.showerror("输入错误", "请选择规范规定的土类及抗拔系数。", parent=self)
            self._cell_editor.focus_set()
            return "break"
        if 0 < column < 6:
            try:
                float(value)
            except ValueError:
                messagebox.showerror("输入错误", "该单元格必须输入数字。", parent=self)
                self._cell_editor.focus_set()
                return "break"
        values = list(self.soil_tree.item(item, "values"))
        values[column] = value
        self.soil_tree.item(item, values=values)
        next_column = max(0, min(6, column + move))
        self._close_cell_editor()
        self._update_soil_sum()
        self._mark_inputs_dirty()
        if move and next_column != column:
            self.after_idle(lambda: self._begin_cell_edit(item, next_column))
        return "break"

    def _close_cell_editor(self) -> str:
        if self._cell_editor is not None:
            tooltip = getattr(self._cell_editor, "_hover_tooltip", None)
            if tooltip is not None:
                tooltip._hide()
            self._cell_editor.destroy()
        self._cell_editor = None
        self._editing_item = None
        return "break"

    def _update_soil_sum(self) -> None:
        total = 0.0
        layers: list[tuple[str, float]] = []
        for item in self.soil_tree.get_children():
            try:
                values = self.soil_tree.item(item, "values")
                thickness = float(values[1])
                if thickness > 0:
                    layers.append((str(values[0]), thickness))
                    total += thickness
            except (ValueError, IndexError):
                pass
        try:
            ht = float(self.vars["embedment"].get())
        except ValueError:
            ht = math.inf
        covered = total >= ht - 1e-6
        self.soil_sum_label.configure(
            text=f"土层总厚度：{total:g} m" + ("" if covered else f"（小于 ht，尚缺 {ht - total:g} m）"),
            foreground="#263238" if covered else "#b42318",
        )
        pile_type = PileType(self.vars["pile_type"].get())
        target_depth = ht
        bearing_name = "桩端持力层"
        basis = "地下计算埋深"
        if pile_type is PileType.HELICAL:
            bearing_name = "最下层叶片端阻土层"
            basis = "最下层叶片埋深"
            try:
                depths = [
                    float(part.strip())
                    for part in self.vars["blade_depths"].get().replace("，", ",").split(",")
                    if part.strip()
                ]
                target_depth = depths[-1]
            except (ValueError, IndexError):
                target_depth = math.inf
        layer_name = "—"
        cumulative = 0.0
        for name, thickness in layers:
            cumulative += thickness
            if target_depth < cumulative + 1e-9:
                layer_name = name
                break
        bearing_covered = total >= target_depth - 1e-6
        if math.isinf(target_depth):
            bearing_text = f"{bearing_name}：无法识别（请检查叶片埋深）"
        elif bearing_covered:
            bearing_text = f"{bearing_name}：{layer_name}（按{basis}自动识别）"
        else:
            bearing_text = f"{bearing_name}：无法识别（土层资料未覆盖至计算位置）"
        self.bearing_layer_label.configure(
            text=bearing_text,
            foreground="#315d83" if bearing_covered and not math.isinf(target_depth) else "#b42318",
        )
        if hasattr(self, "schematic_canvas"):
            self.after_idle(self._draw_schematic)

    def _float(self, key: str, label: str) -> float:
        try:
            return float(self.vars[key].get().strip())
        except ValueError as exc:
            raise InputValidationError([f"{label}必须为数字"]) from exc

    def _collect(self) -> MicropileInput:
        pile_type = PileType(self.vars["pile_type"].get())
        loads = LoadInput(
            self._float("compression", "抗压作用"), self._float("uplift", "抗拔作用"),
            self._float("horizontal", "水平力"),
            self.vars["consider_self_weight"].get() == "1",
        )
        stability_type = StabilitySoilType(self.vars["stability_type"].get())
        common = CommonPileInput(
            diameter_m=self._float("diameter_mm", "桩径") / 1000,
            embedment_m=self._float("embedment", "计算埋深"),
            above_ground_height_m=self._float("height", "桩高出地面的高度h0"),
            top_constraint=PileTopConstraint(self.vars["constraint"].get()),
            allowable_displacement_mm=self._float("displacement", "地面处允许水平位移"),
            width_reduction_factor=self._float("width_factor", "计算宽度折减系数"),
            horizontal_m_mn_m4=self._float("horizontal_m", "m值"),
            horizontal_soil_class=self.vars["soil_class"].get(),
            stability_soil_type=stability_type,
            custom_xi=self._float("xi", "土的侧压力系数ξ") if stability_type is StabilitySoilType.CUSTOM else None,
            pile_tip_condition=PileTipCondition(self.vars["pile_tip_condition"].get()),
            rock_strength_kpa=(
                self._float("rock_strength", "岩石饱和单轴抗压强度标准值")
                if self.vars["pile_tip_condition"].get() == PileTipCondition.ROCK_SURFACE.value
                else None
            ),
        )
        soils: list[SoilLayer] = []
        for item in self.soil_tree.get_children():
            value = self.soil_tree.item(item, "values")
            try:
                soils.append(
                    SoilLayer(
                        name=str(value[0]),
                        uplift_factor=float(str(value[6]).rsplit("：", 1)[-1]),
                        thickness_m=float(value[1]),
                        unit_weight_kn_m3=float(value[2]),
                        beta_deg=float(value[3]),
                        qsik_kpa=float(value[4]),
                        qpk_kpa=float(value[5]),
                    )
                )
            except (ValueError, IndexError) as exc:
                raise InputValidationError([f"土层“{value[0] if value else '?'}”含无效数据"]) from exc
        grouted = None
        helical = None
        if pile_type is PileType.GROUTED:
            grouted = GroutedSection(
                self._float("ec", "混凝土弹性模量"), self._float("es", "钢筋弹性模量"),
                self._float("rho_percent", "配筋率") / 100, self._float("cover_mm", "保护层厚度") / 1000,
            )
        else:
            try:
                depths = tuple(float(part.strip()) for part in self.vars["blade_depths"].get().replace("，", ",").split(",") if part.strip())
            except ValueError as exc:
                raise InputValidationError(["叶片埋深必须是以逗号分隔的数字"]) from exc
            helical = HelicalSection(
                self._float("wall_mm", "钢管壁厚") / 1000, self._float("steel_e", "钢材弹性模量"),
                self._float("blade_diameter_mm", "叶片直径") / 1000, depths,
            )
        return MicropileInput(
            pile_type, loads, common, tuple(soils), grouted, helical,
            project_name=self.vars["project_name"].get().strip(),
        )

    def calculate_action(self, show_errors: bool = True) -> bool:
        if self._cell_editor is not None:
            self._commit_cell_edit()
            if self._cell_editor is not None:
                return False
        try:
            result = calculate(self._collect())
        except (InputValidationError, ValueError) as exc:
            messages = exc.messages if isinstance(exc, InputValidationError) else [str(exc)]
            if show_errors:
                messagebox.showerror("无法计算", "\n".join(f"• {message}" for message in messages), parent=self)
            return False
        self._last_result = result
        if show_errors and result.normalized_input is not None:
            scope_exceedances = micro_short_pile_scope_exceedances(result.normalized_input)
            if scope_exceedances:
                messagebox.showwarning(
                    "超出微型短桩定义范围",
                    "以下输入超出GB 51101-2016第2.1.7条微型短桩基础的定义范围：\n"
                    + "\n".join(f"• {message}" for message in scope_exceedances)
                    + "\n\n程序已继续完成计算，不因此改变验算结论。请用户判断规范适用性及成果是否提交。",
                    parent=self,
                )
        self.report_button.configure(state="normal")
        self._render_result(result)
        return True

    def generate_report_action(self) -> bool:
        if self._last_result is None:
            messagebox.showinfo("请先计算", "请先完成计算并确认界面结果，再生成计算书。", parent=self)
            return False
        project_name = self._last_result.normalized_input.project_name if self._last_result.normalized_input else "微型桩项目"
        safe_name = _safe_filename_stem(project_name, "微型桩项目")
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="生成Word计算书",
            defaultextension=".docx",
            initialfile=f"{safe_name}_微型桩计算书.docx",
            filetypes=(("Word文档", "*.docx"),),
        )
        if not filename:
            return False
        try:
            DocxReportGenerator().generate(self._last_result, Path(filename))
        except (OSError, ValueError, ImportError) as exc:
            messagebox.showerror("生成失败", f"无法生成计算书：\n{exc}", parent=self)
            return False
        messagebox.showinfo("生成完成", f"Word计算书已生成：\n{filename}", parent=self)
        return True

    def _render_result(self, result) -> None:
        for child in self.card_frame.winfo_children():
            child.destroy()
        failed = [check.name for check in result.checks.values() if not check.passed]
        finite_checks = [check for check in result.checks.values() if math.isfinite(check.utilization)]
        controlling = max(finite_checks, key=lambda check: check.utilization) if finite_checks else None
        if failed:
            summary = f"总体结论：不满足；未通过：{'、'.join(failed)}。"
            foreground = "#b42318"
        else:
            summary = "总体结论：抗压、抗拔、水平承载力和整体稳定四项验算均满足。"
            foreground = "#147d3f"
        if controlling is not None:
            summary += f"\n控制验算：{controlling.name}，利用率 {controlling.utilization:.3f}。"
        if result.warnings:
            summary += f" 另有{len(result.warnings)}条警告，请查看中间计算区。"
        self.summary_label.configure(text=summary, foreground=foreground)
        control_labels = {
            "compression": "桩端持力层" if result.pile_type is PileType.GROUTED else "最下层叶片端阻土层",
            "uplift": "主要抗拔贡献层",
            "horizontal": "水平计算土类",
            "stability": "土的侧压力系数",
        }
        result_labels = {
            "compression": (f"桩顶压力 {SYMBOLS['N_MK'].markup}", "竖向承载力 R"),
            "uplift": (
                f"抗拔验算净作用 max({SYMBOLS['T_K'].markup}-{SYMBOLS['G_P'].markup}, 0)",
                f"抗拔承载力 {SYMBOLS['T_UK'].markup}/K",
            ),
            "horizontal": (f"桩顶水平力 {SYMBOLS['H_MIK'].markup}", f"水平承载力 {SYMBOLS['R_HA'].markup}"),
            "stability": (
                f"验算水平力 1.1{SYMBOLS['H_MIK'].markup}",
                f"整体稳定水平抗力 {SYMBOLS['R_H'].markup}",
            ),
        }

        def number(key: str) -> float | None:
            value = result.intermediates.get(key)
            return value if isinstance(value, (int, float)) else None

        q_side = number("竖向总极限侧阻力 Qsk (kN)")
        if q_side is None:
            q_side = number("螺旋桩有效侧阻力 (kN)")
        q_tip = number("桩端极限阻力 Qpk (kN)")
        if q_tip is None:
            q_tip = number("叶片端阻力 (kN)")
        q_ultimate = number("抗压极限承载力 Quk (kN)")
        t_ultimate = number("抗拔极限承载力 Tuk (kN)")
        adopted_gp = number("抗拔验算采用单桩自重 Gp (kN)")
        q_ultimate_symbol = SYMBOLS["Q_UK"].markup
        detail_lines = {
            "compression": [
                f"极限承载力 {q_ultimate_symbol}={q_ultimate:.3f} kN" if q_ultimate is not None else "",
                (
                    f"{SYMBOLS['Q_SK'].markup}={q_side:.3f} kN；{SYMBOLS['Q_PK'].markup}={q_tip:.3f} kN"
                    if result.pile_type is PileType.GROUTED and q_side is not None and q_tip is not None
                    else f"有效侧阻={q_side:.3f} kN；叶片端阻={q_tip:.3f} kN"
                    if q_side is not None and q_tip is not None else ""
                ),
            ],
            "uplift": [
                f"极限抗拔力 {SYMBOLS['T_UK'].markup}={t_ultimate:.3f} kN" if t_ultimate is not None else "",
                (
                    f"桩顶拔力 {SYMBOLS['T_K'].markup}={result.normalized_input.loads.uplift_kn:.3f} kN；"
                    + (
                        f"验算采用 {SYMBOLS['G_P'].markup}={adopted_gp:.3f} kN"
                        if result.normalized_input.loads.consider_pile_self_weight
                        else f"本程序保守取 {SYMBOLS['G_P'].markup}=0"
                    )
                    if result.normalized_input is not None and adopted_gp is not None else ""
                ),
                "抗拔安全系数取2.0",
            ],
            "horizontal": [
                (
                    f"α={number('水平变形系数 α (1/m)'):.4f} 1/m；"
                    f"αh={number('换算埋深 αh'):.3f}"
                    if number("水平变形系数 α (1/m)") is not None else "水平力为0，无需验算"
                ),
                (
                    f"地面处位移 x₀k={number('标准组合水平力下地面处位移 x0k (mm)'):.3f} mm；"
                    f"{SYMBOLS['X_0A'].markup}={number('允许水平位移 x0a (mm)'):g} mm"
                    if number("标准组合水平力下地面处位移 x0k (mm)") is not None else ""
                ),
                str(result.intermediates.get("水平验算方法", "")),
            ],
            "stability": [
                (
                    f"{SYMBOLS['R_H'].markup}={number('整体稳定水平抗力 RH (kN)'):.3f} kN；"
                    f"1.1{SYMBOLS['H_MIK'].markup}={result.checks['stability'].demand_kn:.3f} kN"
                    if number("整体稳定水平抗力 RH (kN)") is not None else "水平力为0，无需验算"
                ),
                (
                    f"θ={number('压力扩散角参数 θ'):.4f}；"
                    f"{SYMBOLS['B_0'].markup}={number('整体稳定计算宽度 b0 (m)'):.4f} m"
                    if number("压力扩散角参数 θ") is not None else ""
                ),
            ],
        }
        for index, (check_key, check) in enumerate(result.checks.items()):
            card = ttk.LabelFrame(self.card_frame, text=check.name, padding=8)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)
            capacity = "无需验算" if math.isinf(check.capacity_kn) else f"{check.capacity_kn:.3f} kN"
            utilization = "—" if math.isinf(check.capacity_kn) else f"{check.utilization:.3f}"
            demand_label, capacity_label = result_labels[check_key]
            ttk.Label(card, text="满足" if check.passed else "不满足", style="Pass.TLabel" if check.passed else "Fail.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
            RichFormulaLabel(card, f"{demand_label}：{check.demand_kn:.3f} kN").grid(row=1, column=0, sticky="w")
            RichFormulaLabel(card, f"{capacity_label}：{capacity}").grid(row=2, column=0, sticky="w")
            ttk.Label(card, text=f"利用率：{utilization}").grid(row=3, column=0, sticky="w")
            row = 4
            for line in filter(None, detail_lines[check_key]):
                RichFormulaLabel(card, line, foreground="#34495e").grid(row=row, column=0, sticky="w")
                row += 1
            ttk.Label(card, text=f"{control_labels[check_key]}：{check.controlling_layer}", foreground="#5f6b7a").grid(row=row, column=0, sticky="w")
            ttk.Label(card, text=check.clause, foreground="#5f6b7a", wraplength=250).grid(row=row + 1, column=0, sticky="w")
            self.card_frame.rowconfigure(index // 2, weight=1)
        self.card_frame.columnconfigure((0, 1), weight=1)
        lines = ["【中间量】"]
        for key, value in result.intermediates.items():
            lines.append(f"{key}：{value:.6g}" if isinstance(value, float) else f"{key}：{value}")
        if result.warnings:
            lines.extend(["", "【警告】", *(f"• {warning}" for warning in result.warnings)])
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")


def create_root() -> tk.Tk:
    root = tk.Tk()
    MicropileApp(root)
    _set_window_icon(root)
    return root
