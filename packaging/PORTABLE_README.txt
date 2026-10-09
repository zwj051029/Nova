Nova v0.1.0 — Windows x64 portable edition

Quick start
1. Extract the entire ZIP archive to a writable directory.
2. Keep Nova.exe and the _internal folder together.
3. Run Nova.exe. Python is already included.
4. To try without hardware, open sim:// in the serial page, choose Demo
   in AI tuning, then start an automatic trial.

Safety
This release is unsigned. Verify its SHA-256 checksum against the
SHA256SUMS.txt file on the official GitHub release. Do not disable OS
security protections to run it.
Simulation and software tests are not a substitute for hardware acceptance.
Physical devices require independent limits, watchdog protection and E-stop.
Default profiles are placeholders, not validated hardware safety settings.
Accept/restore only updates RAM parameters and keeps output stopped.

Data and network
Sessions are stored in the Qt application data directory under
tuning_sessions. NOVA_DATA_DIR can override the storage root.
Local optimization requires no network or API key. Optional cloud analysis
uploads only an explicitly approved summary and never controls the device.

Source, documentation and issue reports
https://github.com/zwj051029/Nova

Third-party licenses are included in third_party_licenses.
Qt/PySide6 libraries are dynamically linked and distributed in _internal.
