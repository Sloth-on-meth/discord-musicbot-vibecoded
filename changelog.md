# Changelog

All notable changes to this Discord Music Bot will be documented here.

## [2025-06-06]
### Changed
- Bot now ignores commands sent in the wrong channel (no error, no reply, no log).

## [2025-06-05]
### Added
- Persistent per-user TTS voice selection across restarts (stored in database).
- Music resumes from the exact timestamp after TTS interruptions for seamless playback.
- Database is no longer reset on startup; all queues and user settings are persistent.
- Added and started maintaining this changelog.

### Changed
- Updated README to reflect new persistence and seamless resume features.

### Fixed
- TTS interruptions no longer cause music to restart from the beginning.

---

## [Earlier]
- Initial implementation of music playback, queue, and TTS features.
