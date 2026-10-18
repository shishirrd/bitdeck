# Security

BitDeck is a prototype. Source review and regression tests do not certify it safe.

The portable executable bundles Python and dependencies; no user-installed Python
is required. It is unsigned. The worker remains a separate resource-limited
process embedded in the outer executable, rather than running conversion in the UI.

## Report an issue

Do not attach confidential files or working exploit payloads to public issues.
Once hosted on GitHub, use the repository's private vulnerability reporting if
enabled. Until a private reporting channel is configured, open a public issue
requesting contact without disclosing exploit details. No contact address or
private-reporting availability is assumed by this repository.

## Threat model

The intended user is a standard Windows desktop user processing images, PDFs and
plain text. Input bytes and metadata are untrusted. The app restricts decoder
formats, bytes, pixel dimensions, frame/page counts, output counts and runtime.
Conversion jobs use bounded JSON over private child-process stdin/stdout.
Encoding and source parsing occur in a worker. Workers receive a Windows Job
Object before the UI sends the request that enables parsing.

The parent bounds reply size and elapsed time. Each worker bounds its input and
output bytes, rebuilds metadata-free image pixels and publishes through an exclusive
temporary file plus no-replace Windows rename (hard link on POSIX). Path names are derived from source file
names rather than document-controlled metadata. Results are shown as plain text.

Classic .wsz skins are treated as untrusted ZIP input. The importer limits archive
bytes (8 MiB), expanded sizes (24 MiB), member count (128), individual members
(4 MiB), bitmap dimensions (1024×1024) and suspicious compression ratios. It rejects
unsafe paths, symlinks, encrypted and ambiguous duplicate assets. No extraction,
scripts, plugins, embedded fonts or cursors are used. Only selected BMP assets and
hex colors are consumed in a worker; a rebuilt PNG header and validated role
colors return to Qt. The cache caps bytes, checks PNG IHDR dimensions before Qt
decoding and never accepts raw QSS, executable code or arbitrary resource URLs.

Single-instance handoff uses a QLocalServer named pipe with UserAccessOption.
It caps messages at 128 KiB, connections at 16, files at 50 and connection time
at 1.5 seconds. Data can open a menu, never choose an action or execute code.
The pipe's ACL behavior is unverified outside this sandbox, where creation is
denied. Drag/drop explicitly uses CopyAction. Mouse/Shift/Escape state is polled;
normal typing is not recorded.

## Out of scope / residual risks

- Workers inherit the user's permissions. A native decoder exploit could access
  that user's files or network. An actual restricted-token/AppContainer design
  remains future work. Never describe the current worker as a secure sandbox.
- The UI decodes a bounded, worker-generated PNG preview through Qt. This still
  creates a parser attack surface if the worker is compromised.
- The app does not defend against a malicious process running as the same user,
  hostile destination-directory symlink/junction replacement, DLL injection,
  modified Python environments, or an administrator.
- The optional image editor binds exports to the SHA-256 of inspected bytes. A changed
  source is rejected until re-inspected. Still inspect exported redactions before
  sharing. Direct core callers can omit the optional fingerprint check.
- Undo's identity check reduces accidental replacement, but is not an atomic
  defense against a local process swapping the path during the check/trash call.
- Cancel is best effort around publication. A force-killed worker may leave a
  temporary file or a finished output. The original remains untouched.
- Network/cloud filesystems may have different publication semantics. A normal
  local NTFS folder is the tested destination. POSIX publication requires hard links.
- PDF Info/XMP removal does not sanitize arbitrary PDF content, annotations,
  attachments, scripts or visible identifiers. Other PDF actions may preserve
  active page content. PDF outputs are not automatically opened.
- Text is printed literally, never interpreted as HTML/Markdown/source code.
  No external resources are fetched. Font coverage and complex scripts are limited.
- Metadata removal does not anonymize visible content or file names, scrub
  filesystem timestamps, or remove metadata from original files.
- Dependency pins/hashes improve repeatability, not immunity to dependency flaws.
  The local portable binary is unsigned; it has not been independently reviewed.

## Release checklist

Run the regression suite on Windows; inspect the screenshot; audit pinned
dependencies; review third-party licenses; document changes to resource limits
or supported formats. A future binary release additionally requires provenance,
checksums, signing, and independent validation of its packaged dependencies.
