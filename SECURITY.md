# Security

Please do not report a vulnerability with live credentials or an unredacted
environment attached. Use the repository's private vulnerability reporting if
the maintainer has enabled it. If unavailable, open an issue requesting a private
contact channel without publishing exploit details or secrets.

Passwords are transient. Stored hints and certificate approvals use Windows
current-user DPAPI with no embedded encryption key or plaintext fallback.
DPAPI is not isolation from another process under the same Windows account.
Review first-use and changed certificate fingerprints through a trusted channel.

Interrupted exports may leave server-side state behind even after the local
process exits. Force-stop is not a server repair operation. The app must never
silently restart host services, disable certificate checks or change VM power.
