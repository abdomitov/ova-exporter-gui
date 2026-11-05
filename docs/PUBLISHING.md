# Publishing OVA Exporter GUI

## Repository identity

- Suggested repository: `ova-exporter-gui`
- Display name: **OVA Exporter GUI**
- About text: **Windows GUI for VMware OVF Tool. Export powered-off VMs from ESXi or vCenter to verified OVA packages, with progress, speed graphs and dark mode.**
- Suggested topics: `ovftool`, `ovf-tool`, `ova`, `ovf`, `vmware`, `esxi`, `vcenter`, `windows`, `gui`, `python`, `tkinter`, `virtual-machine`, `ova-export`.

Use the product name consistently. It is descriptive and easy to understand;
it does not establish exclusive ownership of the words or a trademark clearance.
Keep the independent-project notice visible and avoid vendor logos.

## First release

Once GitHub CLI is signed in locally, `tools/publish_github.ps1` can create the
public repository and push the allowlisted source. It uses the authenticated
account's GitHub noreply address for the commit, sets the About description and
topics, and stops if an existing remote needs review. No token belongs in source.
Upload the Setup executable and SHA-256 sidecar from `dist/` as Release assets;
the installer bundles Python/Tk but requires VMware OVF Tool separately.

1. Review the MIT license and contributor copyright line. Add your preferred
   author credit if desired, and check that you may license all contributed code.
2. Upload the clean source archive's contents, not the entire Desktop installation.
   The archive is built from an explicit allowlist by `tools/package_source.py`.
3. Confirm the repository contains no VMware runtime, exports, caches, private
   addresses, credentials, real-server screenshots or local history.
4. Add screenshots from the isolated fake-data preview, plus a short demonstration
   of the connection, selection and task dashboard flow.
5. Document compatibility actually verified in a disposable lab. Distinguish that
   from fake-data UI checks; do not describe the app as error-free or live-certified.
6. Create a tagged GitHub release, attach the source ZIP and its SHA-256 checksum,
   and explain Python/OVF Tool installation and cancellation limitations.
7. Enable issues, discussions and private vulnerability reporting if appropriate.
   Add a clear support policy before inviting broad production use.

## Free discovery

GitHub topics help users find related repositories; see
[GitHub's topic guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).
Use relevant terms naturally in the repository title, About text, README, release
notes and screenshot descriptions: “OVF Tool GUI,” “ESXi OVA export” and “vCenter
OVA export.” Include clear setup steps, useful troubleshooting and honest limits.

Publish a short walkthrough and share it in relevant VMware/homelab/developer
communities that allow project announcements. Explain the problem it solves,
provide a working example, and invite feedback. Avoid duplicate spam, purchased
stars, invented reviews or keyword stuffing.

A small documentation site can use **GitHub Pages free with a public GitHub Free
repository**; see [GitHub Pages quickstart](https://docs.github.com/en/pages/quickstart).
An ordinary repository README and release page are a practical starting point.
No website or repository is published by the local packaging script.

Google inclusion does not require payment, but neither indexing nor first-place
ranking is guaranteed. Useful content, accurate page titles and genuine links
help discovery; see [Google Search Essentials](https://developers.google.com/search/docs/essentials).
Broad terms such as “OVF Tool” compete with the vendor and established tools;
“OVA Exporter GUI for ESXi on Windows” is a more precise description to target.

## Next product ideas

Prioritize richer actionable errors, destination capacity checks, accessible
keyboard navigation and localization. A later release could add a signed Windows
installer and an authorized lab compatibility matrix. Resumable transfer, remote
deployment and automatic recovery need separate technical designs and validation;
do not promise them based on the current exporter.
