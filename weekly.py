#!/usr/bin/env python3
# Copyright (C) 2026 arch-Ada <arch.ada@systemli.org>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Weekly summary building for calorieCounter."""

import logging
from datetime import datetime, timezone

LOGGER = logging.getLogger(__name__)


def build_last_week_summary(storage):
    """Build a tracked-period summary and per-day net values for graph bars."""
    now = datetime.now(timezone.utc).astimezone()
    today = now.date()
    start_day = today.fromordinal(today.toordinal() - 6)
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=now.tzinfo)
    totals_net = {}
    day_has_data = {}
    for offset in range(7):
        day = start_day.fromordinal(start_day.toordinal() + offset)
        key = day.isoformat()
        totals_net[key] = 0
        day_has_data[key] = False

    first_session_event_ts = None

    try:
        for item in storage.iter_recent_session_events(window_start):
            action = item.get('action')
            if action not in ('add', 'subtract', 'reset', 'init'):
                continue
            timestamp = storage.parse_iso_datetime(item.get('timestamp'))
            if timestamp is None:
                continue
            day_key = timestamp.date().isoformat()
            if day_key not in totals_net:
                continue
            try:
                delta = int(item.get('delta', 0))
            except (TypeError, ValueError):
                continue
            if first_session_event_ts is None or timestamp < first_session_event_ts:
                first_session_event_ts = timestamp
            day_has_data[day_key] = True
            totals_net[day_key] += delta
    except OSError:
        LOGGER.exception('Failed to read weekly summary from session log: %s', storage.session_log_path)
        return 'Failed to read weekly summary.'

    if first_session_event_ts is not None:
        tracked_start = first_session_event_ts
    else:
        tracked_start = window_start

    tracked_start_day = tracked_start.date()
    lines = []
    daily_bars = []
    total_net = 0
    days_count = 0
    any_tracking = first_session_event_ts is not None
    for offset in range(7):
        day = start_day.fromordinal(start_day.toordinal() + offset)
        day_key = day.isoformat()
        if day < tracked_start_day:
            continue
        if not any_tracking:
            continue
        day_net = totals_net.get(day_key, 0)
        total_net += day_net
        days_count += 1
        if day_has_data.get(day_key, False):
            lines.append(f'{day_key} ({day.strftime("%a")}): net {day_net:+d} kcal')
            daily_bars.append(
                {
                    'day_key': day_key,
                    'label': day.strftime('%a'),
                    'net': day_net,
                }
            )
        else:
            lines.append(f'{day_key} ({day.strftime("%a")}): no data')

    lines.append('')
    if days_count == 0:
        lines.append('No tracked data in the last 7 days.')
    else:
        lines.append(f'Tracked-period net: {total_net:+d} kcal')
        lines.append(f'Tracked-period average net: {total_net / float(days_count):+.1f} kcal/day')

    return {
        'text': '\n'.join(lines),
        'daily_bars': daily_bars,
    }
