# Changelog

All notable changes to this project are documented in this file.

## 2026-02-15
- Added persistent state and single-instance lock handling.
- Added session click logging with automatic 7-day pruning.
- Added weekly overview with net-per-day summary and event graph.
- Added menu actions for viewing and clearing active/archive logs.
- Added adjustable click amounts.
- Added GPL-3.0 licensing and project documentation updates.
- Updated weekly overview dialog to show active-session calories.
- Unified archive view formatting with active log view formatting.
- Removed migration-only data handling and aligned docs with current log format.

## 2026-02-17
- Added weekly graph average reference line (cyan) using tracked-period average net kcal/day.
- Added user-facing error dialogs when click log writes fail.
- Added user-facing error dialog when archive clear fails.
- Reduced duplicated UI/state persistence code paths in the tray controller.
