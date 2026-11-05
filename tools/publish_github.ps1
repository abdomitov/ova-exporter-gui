param([string]$Repository='ova-exporter-gui',[string]$Python='python')
$ErrorActionPreference='Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & gh auth status
    if ($LASTEXITCODE) { throw 'Sign in locally with gh auth login, then retry.' }
    $account = (& gh api user | ConvertFrom-Json)
    if ($LASTEXITCODE) { throw 'Could not read authenticated GitHub account' }
    if (-not (Test-Path -LiteralPath '.git')) { & git init -b main; if ($LASTEXITCODE) { throw 'git init failed' } }
    & git config user.name $account.login
    & git config user.email ($account.id.ToString()+'+'+$account.login+'@users.noreply.github.com')
    $files = & $Python -c 'from tools.package_source import ROOT_FILES,EXTRA_FILES,OPTIONAL_IMAGES; from pathlib import Path; print("\n".join(ROOT_FILES+EXTRA_FILES+tuple(n for n in OPTIONAL_IMAGES if Path(n).is_file())))'
    if ($LASTEXITCODE) { throw 'Could not obtain public-source allowlist' }
    & git add -- $files
    if ($LASTEXITCODE) { throw 'git add failed' }
    $tracked = & git ls-files
    if ($tracked | Where-Object { $_ -match '(?i)(^|/)(ovftool|artifacts|logs|\.build-tools)/|\.(exe|dll|ova|vmdk|json)$' }) { throw 'Unexpected private/runtime file is tracked. Review before publishing.' }
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 1) { & git commit -m 'Release OVA Exporter GUI'; if ($LASTEXITCODE) { throw 'Commit failed' } }
    if (& git remote) { throw 'An existing remote needs review; no repository was created or pushed.' }
    & gh repo create $Repository --public --source . --remote origin --push --description 'Windows GUI for VMware OVF Tool. Export powered-off ESXi/vCenter VMs to verified OVA packages, with speed graphs and dark mode.'
    if ($LASTEXITCODE) { throw 'Repository creation/push failed. Inspect local and remote state before retrying.' }
    & gh repo edit ($account.login+'/'+$Repository) --add-topic ovftool,ova,vmware,esxi,vcenter,windows,gui,python,tkinter
} finally { Pop-Location }
