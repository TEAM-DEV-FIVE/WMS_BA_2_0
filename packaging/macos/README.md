# Native macOS lab build

Extension requested by the user after B23; baseline Windows acceptance remains separate.
Target in this iteration: **macOS 15, Apple Silicon arm64, CPython 3.12**.
Run `python packaging/macos/build.py` from a clean checkout on a native Mac or GitHub `macos-15` VM.
Dependencies install in a disposable venv from the platform-specific SHA-256 lock.

Output: `dist/macos-<commit12>/WMS-macos-arm64-TEST-ONLY.zip`, provenance, installed smoke and hashes.
PyInstaller embeds Python/Tk, PDFium/Pillow, SQLite migrations and TLS CA roots.
The build re-seals the `.app` with ad-hoc codesign after writing provenance, verifies recursively,
copies it to a Unicode path outside checkout, then exercises Tk, native PDFium, TLS roots and SQLite.
Startup verifies the bundle seal and keeps personal data outside the entire `.app` directory.

**Ad-hoc signing checks integrity only. It is not Developer ID, notarization or public publisher trust.**
No Apple signing certificate/account is configured in repository Actions secrets at preparation time.
Do not disable Gatekeeper or claim this artifact is ready for public distribution.
Full API workflows, macOS CUPS printing, upgrade/reboot and real hardware remain acceptance tasks.
The macOS archive does not implement a signed/notarized DMG installer or Intel/universal support.

Workflow `.github/workflows/native-lab.yml` builds Windows with a short-lived self-signed Code Signing
certificate created inside its disposable VM, and macOS with ad-hoc signing. No private key is exported
or uploaded; Windows trust is removed at job end. Artifacts explicitly use TEST-ONLY names.
The native workflow runs on `build/native-vm` pushes; it does not publish a GitHub release or change main.
