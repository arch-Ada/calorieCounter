#!/usr/bin/env python3
# Copyright (C) 2026 arch-Ada <arch.ada@systemli.org>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistence and locking utilities for calorieCounter."""

import fcntl
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class CalorieStorage:
    """Encapsulates state, log, archive, and single-instance lock handling."""

    def __init__(self, base_dir=None, archive_retention_days=90):
        if base_dir is None:
            base_dir = Path.home() / '.local' / 'state' / 'calorieCounter'
        self.base_dir = base_dir
        self.state_path = self.base_dir / 'state.json'
        self.session_log_path = self.base_dir / 'session_log.jsonl'
        self.archive_log_path = self.base_dir / 'log_archive.jsonl'
        self.lock_path = self.base_dir / 'app.lock'
        self.archive_retention_days = int(archive_retention_days)
        self.lock_fd = None

    def acquire_instance_lock(self):
        """Acquire a non-blocking process lock to enforce single instance."""
        fd = None
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, f'{os.getpid()}\n'.encode('utf-8'))
            self.lock_fd = fd
            return True
        except BlockingIOError:
            LOGGER.error('Another calorieCounter instance is already running.')
            if fd is not None:
                os.close(fd)
            return False
        except OSError:
            LOGGER.exception('Failed to acquire instance lock: %s', self.lock_path)
            if fd is not None:
                os.close(fd)
            return False

    def release_instance_lock(self):
        """Release and close the process lock file descriptor."""
        if self.lock_fd is None:
            return
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        except OSError:
            LOGGER.exception('Failed to release instance lock: %s', self.lock_path)
        try:
            os.close(self.lock_fd)
        except OSError:
            LOGGER.exception('Failed to close instance lock file descriptor.')
        self.lock_fd = None

    def load_state(self, default_left_click_amount, default_right_click_amount):
        """Load persisted state and indicate whether a save is needed."""
        now_local = datetime.now(timezone.utc).astimezone()
        try:
            if self.state_path.exists():
                with self.state_path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    calories = max(0, int(data.get('calories', 0)))
                    left_click_amount = int(data.get('left_click_amount', default_left_click_amount))
                    right_click_amount = int(data.get('right_click_amount', default_right_click_amount))
                    session_start_raw = data.get('session_start')
                    session_start = self.parse_iso_datetime(session_start_raw)
                    needs_persist = False
                    if session_start is None:
                        session_start = now_local
                        needs_persist = True
                    return (
                        calories,
                        max(0, left_click_amount),
                        max(0, right_click_amount),
                        session_start,
                        needs_persist,
                    )
        except json.JSONDecodeError:
            LOGGER.exception('Failed to parse state file: %s', self.state_path)
        except (OSError, ValueError):
            LOGGER.exception('Failed to load state file: %s', self.state_path)
        return (
            0,
            int(default_left_click_amount),
            int(default_right_click_amount),
            now_local,
            True,
        )

    def save_state(self, calories, left_click_amount, right_click_amount, session_start):
        """Persist current counter and session metadata atomically."""
        try:
            self.atomic_write_json(
                self.state_path,
                {
                    'calories': int(calories),
                    'left_click_amount': int(left_click_amount),
                    'right_click_amount': int(right_click_amount),
                    'session_start': session_start.isoformat(timespec='seconds'),
                },
            )
        except OSError:
            LOGGER.exception('Failed to save state file: %s', self.state_path)

    def clear_log(self):
        """Erase the click-event log file atomically."""
        try:
            self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.atomic_write_text(self.session_log_path, '')
            return True
        except OSError:
            LOGGER.exception('Failed to clear log: %s', self.session_log_path)
            return False

    def clear_archive_log(self):
        """Erase the archived log file atomically."""
        try:
            self.archive_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.atomic_write_text(self.archive_log_path, '')
            return True
        except OSError:
            LOGGER.exception('Failed to clear archive log: %s', self.archive_log_path)
            return False

    def append_session_event(self, delta, calories_after, action):
        """Append a log event and prune to the last 7 days."""
        entry = {
            'timestamp': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
            'delta': int(delta),
            'calories_after': int(calories_after),
            'action': action,
        }
        try:
            self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.session_log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except OSError:
            LOGGER.exception('Failed to append session log: %s', self.session_log_path)
            return False
        self.prune_session_log()
        return True

    def ensure_initial_log_entry(self, session_start, calories):
        """Seed the log with one baseline entry on first launch with no log."""
        if self.session_log_has_events():
            return
        entry = {
            'timestamp': session_start.isoformat(timespec='seconds'),
            'delta': 0,
            'calories_after': int(calories),
            'action': 'init',
        }
        try:
            self.session_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.session_log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            LOGGER.exception('Failed to seed initial log entry: %s', self.session_log_path)

    def session_log_has_events(self):
        """Return True when active log has at least one valid timestamped entry."""
        if not self.session_log_path.exists():
            return False
        try:
            with self.session_log_path.open('r', encoding='utf-8') as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if self.parse_iso_datetime(item.get('timestamp')) is not None:
                        return True
        except OSError:
            LOGGER.exception('Failed to inspect session log: %s', self.session_log_path)
        return False

    def prune_session_log(self):
        """Retain last 7 days in active log and archive older valid events."""
        try:
            if not self.session_log_path.exists():
                self.prune_archive_log()
                return

            cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=7)
            kept_lines = []
            archived_lines = []
            with self.session_log_path.open('r', encoding='utf-8') as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    timestamp = self.parse_iso_datetime(item.get('timestamp'))
                    if timestamp is None:
                        continue
                    if timestamp >= cutoff:
                        kept_lines.append(json.dumps(item))
                    else:
                        archived_lines.append(json.dumps(item))

            if archived_lines and not self.append_archive_lines(archived_lines):
                return

            payload = '\n'.join(kept_lines)
            if payload:
                payload += '\n'
            self.atomic_write_text(self.session_log_path, payload)
            self.prune_archive_log()
        except OSError:
            LOGGER.exception('Failed to prune session log: %s', self.session_log_path)

    def append_archive_lines(self, lines):
        """Append archived JSONL lines to the archive file."""
        try:
            self.archive_log_path.parent.mkdir(parents=True, exist_ok=True)
            if not lines:
                return True

            with self.archive_log_path.open('a', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')
                f.flush()
                os.fsync(f.fileno())
            return True
        except OSError:
            LOGGER.exception('Failed to append archive log: %s', self.archive_log_path)
            return False

    def prune_archive_log(self):
        """Retain only recent archive entries up to configured retention window."""
        try:
            if not self.archive_log_path.exists():
                return
            cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=self.archive_retention_days)
            kept_lines = []
            with self.archive_log_path.open('r', encoding='utf-8') as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    timestamp = self.parse_iso_datetime(item.get('timestamp'))
                    if timestamp is None:
                        continue
                    if timestamp >= cutoff:
                        kept_lines.append(json.dumps(item))
            payload = '\n'.join(kept_lines)
            if payload:
                payload += '\n'
            self.atomic_write_text(self.archive_log_path, payload)
        except OSError:
            LOGGER.exception('Failed to prune archive log: %s', self.archive_log_path)

    def read_log_text(self):
        """Return formatted event log text for the retained 7-day window."""
        return self.read_formatted_jsonl_text(
            path=self.session_log_path,
            empty_message='No log events yet.',
            failure_message='Failed to read log.',
        )

    def read_archive_text(self):
        """Return archive log text for display."""
        return self.read_formatted_jsonl_text(
            path=self.archive_log_path,
            empty_message='No archived log events yet.',
            failure_message='Failed to read archive log.',
        )

    def iter_recent_session_events(self, window_start):
        """Yield session events newer than the given start time."""
        if not self.session_log_path.exists():
            return
        with self.session_log_path.open('r', encoding='utf-8') as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                timestamp = self.parse_iso_datetime(item.get('timestamp'))
                if timestamp is None:
                    continue
                if timestamp >= window_start:
                    yield item

    def read_formatted_jsonl_text(self, path, empty_message, failure_message):
        """Return human-readable text from a JSONL event file."""
        if not path.exists():
            return empty_message

        lines = []
        try:
            with path.open('r', encoding='utf-8') as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    timestamp = item.get('timestamp', 'unknown time')
                    try:
                        delta = int(item.get('delta', 0))
                    except (TypeError, ValueError):
                        continue
                    after = item.get('calories_after', '?')
                    sign_delta = f'+{delta}' if delta >= 0 else str(delta)
                    lines.append(f'{timestamp} | {sign_delta} kcal | total={after}')
        except OSError:
            LOGGER.exception('Failed to read log file: %s', path)
            return failure_message

        if not lines:
            return empty_message
        return '\n'.join(lines)

    @staticmethod
    def parse_iso_datetime(value):
        """Parse an ISO datetime string and normalize to local timezone."""
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value).astimezone()
        except ValueError:
            return None

    @staticmethod
    def atomic_write_json(path, payload):
        """Atomically write JSON data to disk with fsync and replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f'.{path.name}.tmp')
        try:
            with tmp_path.open('w', encoding='utf-8') as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    LOGGER.warning('Failed to remove temporary file: %s', tmp_path)

    @staticmethod
    def atomic_write_text(path, text):
        """Atomically write plain text to disk with fsync and replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f'.{path.name}.tmp')
        try:
            with tmp_path.open('w', encoding='utf-8') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    LOGGER.warning('Failed to remove temporary file: %s', tmp_path)
