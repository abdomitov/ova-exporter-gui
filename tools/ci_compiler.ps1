$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Compiler provisioning is restricted to a disposable GitHub-hosted Windows runner.'
}
$compilerInstaller = Join-Path $env:RUNNER_TEMP 'innosetup-7.1.1-x64.exe'
$compilerDirectory = Join-Path $env:RUNNER_TEMP 'ova-inno'
$compilerUrl = 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe'
Invoke-WebRequest -Uri $compilerUrl -OutFile $compilerInstaller
$compilerHash = (Get-FileHash -LiteralPath $compilerInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
if ($compilerHash -ne '8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0') { throw 'Compiler checksum mismatch' }
$signature = Get-AuthenticodeSignature -LiteralPath $compilerInstaller
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') { throw 'Unexpected compiler publisher/signature' }
$process = Start-Process -FilePath $compilerInstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="'+$compilerDirectory+'"')) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw 'Compiler installation failed' }
$compilerPath = Join-Path $compilerDirectory 'ISCC.exe'
if (-not (Test-Path -LiteralPath $compilerPath)) { throw 'Compiler executable missing' }
"OVA_ISCC=$compilerPath" >> $env:GITHUB_ENV
"Inno Setup 7.1.1 compiler SHA-256: $compilerHash" >> $env:GITHUB_STEP_SUMMARY
