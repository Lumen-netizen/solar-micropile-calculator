# 光伏支架微型桩计算程序

当前发布版本：`V1.0.0`。

本程序用于微型灌注桩和等直径叶片钢螺旋桩的规范验算，用户输入标准组合后的包络作用值，程序完成抗压、抗拔、水平承载力（位移控制）和整体稳定（抗倾覆）验算。

计算依据包括 NB/T 10115-2018 第8章、GB 51101-2016 第5.3节和 JGJ 94-2008 第5.7节及附录C。水平验算统一采用附录C表C.0.3-1有限长度桩m法，以地面处水平位移x₀为控制量；桩高出地面的高度h₀通过地面处弯矩参与计算，地上段桩顶附加位移不计入基础位移限值。程序仅估算地基承载力，不采用试验承载力，不验算桩身强度、配筋、压屈和施工扭矩。完成计算并确认结果后，可生成包含输入参数、桩土示意图、验算汇总、分项计算过程和结论的 Word 计算书；必要中间值按计算顺序列入相应分项。

微型短桩定义范围方面，当桩身外径大于300 mm或地下计算埋深（入土桩长）大于5 m时，程序仍继续计算，并仅在App界面提示用户复核规范适用性；该提示不进入计算书，也不改变验算结论。

## 运行

推荐普通用户从 GitHub Releases 下载单文件 EXE，无需安装 Python。源码运行前请先创建 Python 3.12 独立环境并安装依赖；环境准备完成后，可双击项目根目录下的 `Start-Micropile-App.cmd`。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\app.py
```

## 项目参数保存

- `保存项目`：将当前全部界面输入保存为带版本号的 UTF-8 JSON 项目文件，适合长期归档和传递给其他用户。
- `打开项目`：从项目文件恢复全部输入，恢复后重新点击“计算”。
- 正常关闭程序时，当前输入会自动缓存到 `%LOCALAPPDATA%\PVSupportMicropileCalculator\last_session.json`；下次启动自动恢复。首次运行、缓存不存在或损坏时使用程序默认值。
- `恢复默认`：将全部参数、土层及两种桩型的几何参数恢复为程序内置默认值，并清除当前计算结果。
- 单 EXE 运行时的 `_MEI` 解压目录是临时目录，程序不会把项目数据保存在其中。

项目使用 Python 3.12 独立 `.venv`，Tcl/Tk 运行资源保存在 `runtime_tcl`。验证环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_environment.ps1
```

运行自动测试和 GUI 冒烟测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\app.py --smoke-test
```

生成 Windows 单文件 EXE：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_onefile.ps1
```

V1.0.0 成品输出至 `release\V1.0.0`，该目录仅保留可直接运行的单个 EXE 文件。

## 目录

- `src/micropile_app/calculations.py`：独立计算内核与校验
- `src/micropile_app/models.py`：输入、结果数据类和枚举
- `src/micropile_app/gui.py`：Tkinter 界面
- `src/micropile_app/reporting.py`：Word计算书生成服务
- `src/micropile_app/project_io.py`：项目文件及上次会话缓存
- `assets/`：程序窗口图标的 PNG 和 Windows 多尺寸 ICO 资源
- `tests/`：规范公式、边界条件、非法输入和回归测试

规范原文及参考 Excel 因版权和分发范围原因不随源码仓库发布。使用者应自行合法取得 NB/T 10115-2018、GB 51101-2016 和 JGJ 94-2008，并对规范适用性及输入参数负责。

现有 Excel 使用 `3.14` 近似圆周率，程序采用 `math.pi`，竖向承载力约有 0.05% 的差异。Excel 水平验算采用表5.7.2中的手工 `νx`；当前程序采用附录C连续求解。自动回归测试验证：当 `h₀=0、Kₕ=0` 时，`αh=2.6～4.0` 各表格节点反算的 `νx` 与表5.7.2一致；`αh=2.4` 按附录C保留非零桩端约束系数 `Kₕ` 并单独锁定计算结果。
