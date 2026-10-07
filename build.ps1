# Build QQChatBridge.exe (PyInstaller, one folder) and a zip of it.
#   powershell -ExecutionPolicy Bypass -File build.ps1
# Output: dist\QQChatBridge\QQChatBridge.exe and dist\Mac-os-qq-bot-Windows-x64.zip
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv .venv
}
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements-windows.txt pyinstaller
# make sure the UI Automation wrapper exists so it can be bundled
& $py -X utf8 -c "import winapp.uia"

& $py -m PyInstaller --noconfirm --clean --onedir --windowed --name QQChatBridge `
    --icon "winapp\ui\icon.ico" `
    --python-option "X utf8" `
    --add-data "winapp\ui;winapp\ui" `
    --add-data "winapp\pet_art.json;winapp" `
    --collect-submodules comtypes.gen `
    --hidden-import pystray._win32 `
    --hidden-import PIL.ImageTk `
    --exclude-module unittest `
    winapp_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$out = Join-Path $PSScriptRoot "dist\QQChatBridge"
Copy-Item prompts (Join-Path $out "prompts") -Recurse -Force
Copy-Item config.example.json, README.md, LICENSE $out -Force
Copy-Item requirements-browser.txt $out -Force

$zip = Join-Path $PSScriptRoot "dist\Mac-os-qq-bot-Windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
# zipfile (not Compress-Archive, which writes backslashes) with a top-level QQChatBridge folder
$zipper = "import sys,zipfile,pathlib; src=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED,compresslevel=9); [z.write(f,'QQChatBridge/'+f.relative_to(src).as_posix()) for f in sorted(src.rglob('*')) if f.is_file()]; z.close()"
& $py -c $zipper $out $zip
Write-Host "Built $out"
Write-Host "Zip   $zip"
