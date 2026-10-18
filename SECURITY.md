# Security

BitDeck is a prototype. Source review and regression tests do not certify it safe.

## Report an issue

Do not attach confidential files or working exploit payloads to public issues.
Once hosted on GitHub, use the repository's private vulnerability reporting if
enabled. Until a private reporting channel is configured, open a public issue
requesting contact without disclosing exploit details. No contact address or
private-reporting availability is assumed by this repository.

## Threat model

The intended user is a standard Windows desktop user processing personal images.
Input image bytes and metadata are untrusted. The app restricts decoder formats,
bytes, pixel dimensions, frame count and runtime. It passes structured JSON over
private child-process stdin/stdout, not a shared listening socket or shell.
Encoding and source parsing occur in a worker. Workers receive a Windows Job
Object before the UI sends the request that enables parsing.

The parent bounds reply size and elapsed time. Each worker bounds its input and
output bytes, rebuilds metadata-free pixels and publishes through an exclusive
temporary file plus no-replace Windows rename (hard link on POSIX). Path names are derived from source file
names rather than document-controlled metadata. Results are shown as plain text.

## Out of scope / residual risks

- Workers inherit the user's permissions. A native decoder exploit could access
  that user's files or network. An actual restricted-token/AppContainer design
  remains future work. Never describe the current worker as a secure sandbox.
- The UI decodes a bounded, worker-generated PNG preview through Qt. This still
  creates a parser attack surface if the worker is compromised.
- The app does not defend against a malicious process running as the same user,
  hostile destination-directory symlink/junction replacement, DLL injection,
  modified Python environments, or an administrator.
- The UI binds exports to the SHA-256 of the inspected source bytes. A changed
  source is rejected until re-inspected. Still inspect exported redactions before
  sharing. Direct core callers can omit the optional fingerprint check.
- Undo's identity check reduces accidental replacement, but is not an atomic
  defense against a local process swapping the path during the check/trash call.
- Cancel is best effort around publication. A force-killed worker may leave a
  temporary file or a finished output. The original remains untouched.
- Network/cloud filesystems may have different publication semantics. A normal
  local NTFS folder is the tested destination. POSIX publication requires hard links.
- Metadata removal does not anonymize visible content or file names, scrub
  filesystem timestamps, or remove metadata from the original file.
- Dependency pins/hashes improve repeatability, not immunity to dependency flaws.
  No binaries are signed or distributed in this initial prototype.

## Release checklist

Run the regression suite on Windows; inspect the screenshot; audit pinned
dependencies; review third-party licenses; document changes to resource limits
or supported formats. A future binary release additionally requires provenance,
checksums, signing, and independent validation of its packaged dependencies.
