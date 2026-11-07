# Publishing app updates

## Automated delivery path

Use **Actions → Build Windows release candidate → Run workflow** on `main`.
The default `create_draft=false` runs the tests/build/installer checks and uploads
seven-day artifacts without creating or publishing an app update. For a reviewed
new app version, use `create_draft=true` to prepare a draft after all checks pass.
Existing versions are never overwritten.

After reviewing that draft and its exact build commit, **Publish reviewed release**
can publish it only with the matching tag, current-main commit and explicit
`confirm_publish=true`. It rechecks the source/files, build manifest and successful
build run. This is a manual approval boundary; nothing auto-publishes on a push.
See [the DevOps learning path](DEVOPS_PATH.md) for commands, scope and downsides.
The manual commands below remain useful for understanding and recovery.

## How delivery works

GitHub hosts the update feed and installer files. No separate server or always-on
maintainer PC is required. Every installed app version 2.3.0 or later can query
the public release list, compare versions, and offer a newer Windows installer.
Updates require user approval: they are not silently installed.

A source push, a Git tag or a source-only release is not enough. The updater
requires a published, non-draft release with both of these uploaded assets:

- `OVA-Exporter-GUI-X.Y.Z-Windows-x64-Setup.exe`
- `OVA-Exporter-GUI-X.Y.Z-Windows-x64-Setup.exe.sha256`

Use a numeric version such as `2.3.1` and a matching tag such as `v2.3.1`.
The checksum file must contain the SHA-256 digest and the exact installer filename.
The build script generates it. Do not rename the installer after building it.

The current updater also includes published preview releases. Marking a release
as a prerelease does not restrict it to testers. Keep unvalidated builds in a
draft until ready for all users. The updater examines the 30 most recent releases.

## Prepare and validate

1. Make and review changes on a branch. Increase `VERSION` in `src/metadata.py`
   and the fallback version in `packaging/windows.iss`. Update the current
   download links in README.md and installer documentation.
2. Run the guarded offline tests and fake-data UI check. These do not need a
   VMware server and must not be pointed at a production environment.
3. Build the Windows installer and source ZIP using the existing tools. Python
   build dependencies and Inno Setup are required; see [Windows installer](WINDOWS_INSTALLER.md).

```powershell
python tools/offline_tests.py
python tools/preview_ui.py --check
.\tools\build_windows.ps1 -Python python -Iscc 'C:\Path\To\ISCC.exe'
python tools/package_source.py
```

4. Run the frozen app's fake-only self-test described in the installer guide.
   Check the installer and source SHA-256 sidecars. Never include VMware OVF Tool,
   local connection settings, OVA exports, credentials or build caches in source.
5. Commit and push the reviewed changes, following any required pull-request
   rules, and wait for the Python 3.10/3.14 GitHub checks to pass.

## Upload and publish

From the tested source checkout, with GitHub CLI authenticated:

```powershell
$releaseVersion = (python -c 'import sys; sys.path.insert(0,"src"); from metadata import VERSION; print(VERSION)').Trim()
$releaseTag = "v$releaseVersion"
$releaseCommit = (git rev-parse HEAD).Trim()
$releaseInstaller = "dist/OVA-Exporter-GUI-$releaseVersion-Windows-x64-Setup.exe"
$releaseSource = "dist/ova-exporter-gui-$releaseVersion-source.zip"
```

Prepare a release-notes file describing the actual changes, checks and limitations,
then create a draft containing all four release files:

```powershell
gh release create $releaseTag --repo abdomitov/ova-exporter-gui `
  --target $releaseCommit --draft --prerelease `
  --title "$releaseTag - Windows preview" --notes-file release-notes.md `
  $releaseInstaller "$releaseInstaller.sha256" $releaseSource "$releaseSource.sha256"
```

Review the uploaded names, sizes, digests and target commit before publishing:

```powershell
gh release view $releaseTag --repo abdomitov/ova-exporter-gui
gh release edit $releaseTag --repo abdomitov/ova-exporter-gui --draft=false
```

All users with update checks enabled can discover this release through GitHub.
This is a client check, not a server push: automatic checking happens once at
startup. An app already open must use **Updates → Check for updates…** or restart.
Automatic checks can be disabled, deferred for a day or skip a particular version.
A manual check overrides the reminder/skip choices. Offline users can still export;
GitHub access is needed to check and download updates.

## Validate the installed-app journey

Keep an older version installed on a test PC and finish its export tasks first.
After publishing the newer release:

1. Open **Updates → Check for updates…** in the older app. Confirm both versions
   in the prompt. Do not alter the installed files to fake an older version.
2. In an installed 2.3.2 or later app, choose **Update**. It downloads the asset,
   verifies size/checksum, installs with a progress window when idle, and reopens.
   Existing folder/shortcut settings are retained; first-install pages are skipped.
3. If any tasks or export setup remain open, installation is deferred until they
   finish and you choose **Install now**. Older 2.3.0/2.3.1 apps open the regular
   wizard once to obtain the improved updater. Source/portable copies also retain
   that wizard. An unsigned installer may still trigger Windows security checks;
   do not disable security protections.
4. Open the installed app. Verify its new version in the title/footer and check
   again; the same version must not be offered as a new update.

Record detection, download, checksum, installer handoff and successful upgrade as
separate checks. A successful download alone does not prove installation succeeded.
Do not test server cancellation or VM power operations as part of this procedure.

## Correcting a bad release

Stop offering a defective release by removing it from published releases through
the normal GitHub release-management process, then publish a corrected build with
a higher version. Removing a release cannot undo copies already downloaded or
installed. The updater never automatically downgrades an installed application.
Avoid replacing a public installer under an existing version: users may have
already downloaded or verified it. Publish a new patch instead.
