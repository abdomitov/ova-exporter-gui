param([string]$Python='python', [string]$Iscc='iscc')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python tools/make_icons.py
    if ($LASTEXITCODE) { throw 'Icon build failed' }
    $assets=Join-Path $projectRoot 'assets'
    & $Python -m PyInstaller --noconfirm --windowed --onedir --name OVAExporterGUI --paths (Join-Path $projectRoot 'src') --icon (Join-Path $assets 'app.ico') --add-data "${assets}:assets" --hidden-import tools.preview_ui --specpath build launch.pyw
    if ($LASTEXITCODE) { throw 'Application build failed' }
    & $Python tools/runtime_licenses.py dist/OVAExporterGUI/licenses
    if ($LASTEXITCODE) { throw 'Runtime license collection failed' }
    $appVersion=(& $Python -c 'import sys; sys.path.insert(0,"src"); from metadata import VERSION; print(VERSION)').Trim()
    & $Iscc "/DAppVersion=$appVersion" packaging/windows.iss
    if ($LASTEXITCODE) { throw 'Installer build failed' }
    $installer=Join-Path 'dist' "OVA-Exporter-GUI-$appVersion-Windows-x64-Setup.exe"
    $digest=(Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    ($digest+'  '+(Split-Path -Leaf $installer)) | Set-Content -LiteralPath ($installer+'.sha256') -Encoding ascii
    Write-Output "Built $installer"
} finally { Pop-Location }
