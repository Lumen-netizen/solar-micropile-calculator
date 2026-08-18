$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AppName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5YWJ5LyP5pSv5p625b6u5Z6L5qGp6K6h566X56iL5bqP"))
$AppVersion = "1.0.0"
$ReleaseExeName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5YWJ5LyP5pSv5p625b6u5Z6L5qGp6K6h566X56iL5bqPX1YxLjAuMC5leGU="))
$ReleaseDir = Join-Path $ProjectDir "release\V$AppVersion"
$WorkDir = Join-Path $ProjectDir "build\pyinstaller-v$AppVersion"
$SpecDir = Join-Path $ProjectDir "build\spec"

if (!(Test-Path -LiteralPath $Python)) {
    throw "Project-local Python was not found: $Python"
}

$PythonRoot = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$StdlibDir = (& $Python -c "import sysconfig; print(sysconfig.get_path('stdlib'))").Trim()
$DllDir = Join-Path $PythonRoot "DLLs"
$TkinterPackage = Join-Path $StdlibDir "tkinter"
$TkinterPyd = Join-Path $DllDir "_tkinter.pyd"
$TclDll = Join-Path $DllDir "tcl86t.dll"
$TkDll = Join-Path $DllDir "tk86t.dll"
$TclData = Join-Path $ProjectDir "runtime_tcl\tcl8.6"
$TkData = Join-Path $ProjectDir "runtime_tcl\tk8.6"
$Assets = Join-Path $ProjectDir "assets"
$Hooks = Join-Path $ProjectDir "packaging_hooks"
$EntryPoint = Join-Path $ProjectDir "app.py"
$SourceDir = Join-Path $ProjectDir "src"
$Icon = Join-Path $ProjectDir "assets\micropile_app_icon.ico"
$VersionInfo = Join-Path $ProjectDir "version_info.txt"

foreach ($RequiredPath in @($TkinterPackage, $TkinterPyd, $TclDll, $TkDll, $TclData, $TkData, $Assets, $Hooks, $EntryPoint, $SourceDir, $Icon, $VersionInfo)) {
    if (!(Test-Path -LiteralPath $RequiredPath)) {
        throw "Required packaging input was not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
New-Item -ItemType Directory -Path $SpecDir -Force | Out-Null

Push-Location $ProjectDir
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name $AppName `
        --paths $SourceDir `
        --icon $Icon `
        --version-file $VersionInfo `
        --distpath $ReleaseDir `
        --workpath $WorkDir `
        --specpath $SpecDir `
        --add-data "$Assets;assets" `
        --add-data "$TkinterPackage\*.py;tkinter" `
        --add-data "$TclData;_tcl_data" `
        --add-data "$TkData;_tk_data" `
        --additional-hooks-dir $Hooks `
        --add-binary "$TkinterPyd;." `
        --add-binary "$TclDll;." `
        --add-binary "$TkDll;." `
        --hidden-import "_tkinter" `
        --hidden-import "PIL._tkinter_finder" `
        $EntryPoint
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $BuiltExe = Join-Path $ReleaseDir "$AppName.exe"
    $ReleaseExe = Join-Path $ReleaseDir $ReleaseExeName
    if (!(Test-Path -LiteralPath $BuiltExe)) {
        throw "Built executable was not found: $BuiltExe"
    }
    Move-Item -LiteralPath $BuiltExe -Destination $ReleaseExe -Force
    Write-Host "Release executable: $ReleaseExe"
}
finally {
    Pop-Location
}
