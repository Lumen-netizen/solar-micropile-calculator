$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$env:TCL_LIBRARY = Join-Path $ProjectDir "runtime_tcl\tcl8.6"
$env:TK_LIBRARY = Join-Path $ProjectDir "runtime_tcl\tk8.6"

if (!(Test-Path -LiteralPath $Python)) {
    throw "Project-local Python was not found: $Python"
}

& $Python -c "import sys, tkinter; assert sys.version_info[:2] == (3, 12); root=tkinter.Tk(); root.withdraw(); root.destroy(); print(sys.executable); print(sys.version); print('Tk', tkinter.TkVersion)"
& $Python -m PyInstaller --version
& $Python -m pip check
