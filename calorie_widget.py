#!/usr/bin/env python3
# Copyright (C) 2026 arch-Ada <arch.ada@systemli.org>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tray-based calorie counter with persistent state and session logging."""

from datetime import datetime, timezone

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf, GLib
import cairo
from storage import CalorieStorage
from weekly import build_last_week_summary as build_weekly_summary

class CalorieTray:
    """GTK tray widget for tracking calories with a single event log."""

    DEFAULT_LEFT_CLICK_AMOUNT = 50
    DEFAULT_RIGHT_CLICK_AMOUNT = 10
    ARCHIVE_RETENTION_DAYS = 90

    def __init__(self):
        """Initialize paths, state, tray icons, and menu actions."""
        self.storage = CalorieStorage(archive_retention_days=self.ARCHIVE_RETENTION_DAYS)
        if not self.storage.acquire_instance_lock():
            raise SystemExit(1)
        (
            self.calories,
            self.left_click_amount,
            self.right_click_amount,
            self.session_start,
            state_needs_persist,
        ) = self.storage.load_state(
            default_left_click_amount=self.DEFAULT_LEFT_CLICK_AMOUNT,
            default_right_click_amount=self.DEFAULT_RIGHT_CLICK_AMOUNT,
        )
        if state_needs_persist:
            self.storage.save_state(
                self.calories,
                self.left_click_amount,
                self.right_click_amount,
                self.session_start,
            )
        self.storage.prune_session_log()
        self.storage.ensure_initial_log_entry(self.session_start, self.calories)

        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_visible(True)
        self.status_icon.connect('activate', self.on_left_click)
        self.status_icon.connect('popup-menu', self.on_right_click)

        self.menu_icon = Gtk.StatusIcon()
        self.menu_icon.set_visible(True)
        self.menu_icon.connect('activate', self.on_menu_icon_activate)
        self.menu_icon.connect('popup-menu', self.on_menu_icon_popup)

        self.menu = Gtk.Menu()

        self.reset_item = Gtk.MenuItem(label='Reset')
        self.reset_item.connect('activate', self.on_reset)
        self.menu.append(self.reset_item)

        self.log_item = Gtk.MenuItem(label='View Log')
        self.log_item.connect('activate', self.on_view_log)
        self.menu.append(self.log_item)

        self.week_item = Gtk.MenuItem(label='View Last Week')
        self.week_item.connect('activate', self.on_view_last_week)
        self.menu.append(self.week_item)

        self.clear_log_item = Gtk.MenuItem(label='Clear Log')
        self.clear_log_item.connect('activate', self.on_clear_log)
        self.menu.append(self.clear_log_item)

        self.view_archive_item = Gtk.MenuItem(label='View Archive')
        self.view_archive_item.connect('activate', self.on_view_archive)
        self.menu.append(self.view_archive_item)

        self.clear_archive_item = Gtk.MenuItem(label='Clear Archive')
        self.clear_archive_item.connect('activate', self.on_clear_archive)
        self.menu.append(self.clear_archive_item)

        self.adjust_click_item = Gtk.MenuItem(label='Adjust Click Amounts')
        self.adjust_click_item.connect('activate', self.on_adjust_click_amounts)
        self.menu.append(self.adjust_click_item)

        self.quit_item = Gtk.MenuItem(label='Quit')
        self.quit_item.connect('activate', self.on_quit)
        self.menu.append(self.quit_item)

        self.menu.show_all()
        self.refresh_icon()
        self.refresh_menu_icon()

    def icon_text(self):
        """Return a compact calorie label suitable for a small tray icon."""
        # Compact number to fit small tray icon.
        if self.calories >= 1000:
            return f"{self.calories // 1000}k"
        return str(self.calories)

    def render_icon(self, width=28, height=22):
        """Render the main tray icon showing the current calorie value."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)

        # Dark pill-shaped badge background, slightly wider than tall.
        radius = (height / 2) - 1
        x = 1
        y = 1
        w = width - 2
        h = height - 2

        cr.set_source_rgba(0.08, 0.09, 0.12, 1.0)
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -3.14159265359 / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, 3.14159265359 / 2)
        cr.arc(x + radius, y + h - radius, radius, 3.14159265359 / 2, 3.14159265359)
        cr.arc(x + radius, y + radius, radius, 3.14159265359, 3 * 3.14159265359 / 2)
        cr.close_path()
        cr.fill()

        # Subtle border for contrast.
        cr.set_source_rgba(0.25, 0.27, 0.33, 1.0)
        cr.set_line_width(1.0)
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -3.14159265359 / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, 3.14159265359 / 2)
        cr.arc(x + radius, y + h - radius, radius, 3.14159265359 / 2, 3.14159265359)
        cr.arc(x + radius, y + radius, radius, 3.14159265359, 3 * 3.14159265359 / 2)
        cr.close_path()
        cr.stroke()

        text = self.icon_text()

        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        font_size = 9 if len(text) <= 2 else 8
        if len(text) >= 4:
            font_size = 7
        cr.set_font_size(font_size)

        ext = cr.text_extents(text)
        tx = (width - ext.width) / 2 - ext.x_bearing
        ty = (height - ext.height) / 2 - ext.y_bearing

        cr.set_source_rgba(0.90, 0.92, 0.96, 1.0)
        cr.move_to(tx, ty)
        cr.show_text(text)

        return self.pixbuf_from_surface(surface, width, height)

    def render_menu_icon(self, size=16):
        """Render the small menu launcher icon with an 'M' label."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)

        cr.set_source_rgba(0.10, 0.11, 0.15, 1.0)
        cr.arc(size / 2, size / 2, (size / 2) - 1, 0, 2 * 3.14159265359)
        cr.fill()

        cr.set_source_rgba(0.28, 0.30, 0.36, 1.0)
        cr.set_line_width(1.0)
        cr.arc(size / 2, size / 2, (size / 2) - 1, 0, 2 * 3.14159265359)
        cr.stroke()

        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(9)
        ext = cr.text_extents('M')
        tx = (size - ext.width) / 2 - ext.x_bearing
        ty = (size - ext.height) / 2 - ext.y_bearing
        cr.set_source_rgba(0.90, 0.92, 0.96, 1.0)
        cr.move_to(tx, ty)
        cr.show_text('M')

        return self.pixbuf_from_surface(surface, size, size)

    def refresh_icon(self):
        """Refresh the main tray icon image and tooltip text."""
        pixbuf = self.render_icon()
        self.status_icon.set_from_pixbuf(pixbuf)
        self.status_icon.set_tooltip_text(
            f"Calories: {self.calories} kcal | Left click: +{self.left_click_amount} | "
            f"Right click: -{self.right_click_amount} | Use M for menu"
        )

    def refresh_menu_icon(self):
        """Refresh the menu launcher icon."""
        self.menu_icon.set_from_pixbuf(self.render_menu_icon())
        self.menu_icon.set_tooltip_text('Menu')

    def on_left_click(self, _icon):
        """Add calories on main-icon left click and persist state."""
        self.calories += self.left_click_amount
        self.storage.append_session_event(self.left_click_amount, self.calories, 'add')
        self.storage.save_state(
            self.calories,
            self.left_click_amount,
            self.right_click_amount,
            self.session_start,
        )
        self.refresh_icon()

    def on_right_click(self, _icon, _button, _event_time):
        """Subtract calories on main-icon right click, clamped at zero."""
        before = self.calories
        self.calories = max(0, self.calories - self.right_click_amount)
        actual_subtract = before - self.calories
        if actual_subtract > 0:
            self.storage.append_session_event(-actual_subtract, self.calories, 'subtract')
        self.storage.save_state(
            self.calories,
            self.left_click_amount,
            self.right_click_amount,
            self.session_start,
        )
        self.refresh_icon()

    def show_menu(self, icon=None, button=0, event_time=None):
        """Open the context menu at the proper tray position."""
        if event_time is None:
            event_time = Gtk.get_current_event_time()
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon or self.menu_icon, button, event_time)

    def on_menu_icon_activate(self, icon):
        """Open the menu when the menu icon is activated."""
        self.show_menu(icon=icon)

    def on_menu_icon_popup(self, icon, button, event_time):
        """Open the menu for menu-icon popup-menu events."""
        self.show_menu(icon=icon, button=button, event_time=event_time)

    def on_reset(self, _item):
        """Reset the current session and record a reset event in the log."""
        reset_time = datetime.now(timezone.utc).astimezone()
        if not self.storage.append_session_event(0, 0, 'reset'):
            self.show_error_dialog(
                'Reset Failed',
                'Could not write reset event to log. Session was not reset to avoid data loss.',
            )
            return
        self.calories = 0
        self.session_start = reset_time
        self.storage.save_state(
            self.calories,
            self.left_click_amount,
            self.right_click_amount,
            self.session_start,
        )
        self.refresh_icon()

    def on_view_log(self, _item):
        """Display click-by-click log events retained for the last 7 days."""
        text = self.storage.read_log_text()
        self.show_text_dialog('Log (Last 7 Days)', text)

    def on_view_last_week(self, _item):
        """Display last-7-days per-day calorie totals in a dialog."""
        summary = build_weekly_summary(self.storage)
        if isinstance(summary, str):
            self.show_text_dialog('Last 7 Days', summary)
            return
        self.show_last_week_dialog(summary)

    def on_clear_log(self, _item):
        """Ask for confirmation, then clear the click-event log."""
        confirm = Gtk.MessageDialog(
            None,
            Gtk.DialogFlags.MODAL,
            Gtk.MessageType.WARNING,
            Gtk.ButtonsType.NONE,
            'Clear entire log?',
        )
        confirm.format_secondary_text('This will permanently remove retained click events.')
        confirm.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            'Clear Log',
            Gtk.ResponseType.OK,
        )
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.OK:
            return
        if self.storage.clear_log():
            self.session_start = datetime.now(timezone.utc).astimezone()
            self.storage.save_state(
                self.calories,
                self.left_click_amount,
                self.right_click_amount,
                self.session_start,
            )

    def on_clear_archive(self, _item):
        """Ask for confirmation, then clear the archived log file."""
        confirm = Gtk.MessageDialog(
            None,
            Gtk.DialogFlags.MODAL,
            Gtk.MessageType.WARNING,
            Gtk.ButtonsType.NONE,
            'Clear archived log?',
        )
        confirm.format_secondary_text('This permanently removes all archived log entries.')
        confirm.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            'Clear Archive',
            Gtk.ResponseType.OK,
        )
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.storage.clear_archive_log()

    def on_view_archive(self, _item):
        """Display archived log entries in a scrollable dialog."""
        text = self.storage.read_archive_text()
        self.show_text_dialog('Archive Log', text)

    def on_quit(self, _item):
        """Release resources and stop the GTK main loop."""
        self.storage.release_instance_lock()
        Gtk.main_quit()

    def on_adjust_click_amounts(self, _item):
        """Show a dialog to edit left/right click calorie step amounts."""
        dialog = Gtk.Dialog(
            title='Adjust Click Amounts',
            parent=None,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,
            Gtk.ResponseType.OK,
        )

        content = dialog.get_content_area()
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=10)
        content.add(grid)

        left_label = Gtk.Label(label='Left click adds:')
        left_label.set_halign(Gtk.Align.START)
        left_input = Gtk.SpinButton.new_with_range(0, 5000, 1)
        left_input.set_value(self.left_click_amount)

        right_label = Gtk.Label(label='Right click subtracts:')
        right_label.set_halign(Gtk.Align.START)
        right_input = Gtk.SpinButton.new_with_range(0, 5000, 1)
        right_input.set_value(self.right_click_amount)

        grid.attach(left_label, 0, 0, 1, 1)
        grid.attach(left_input, 1, 0, 1, 1)
        grid.attach(right_label, 0, 1, 1, 1)
        grid.attach(right_input, 1, 1, 1, 1)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.left_click_amount = int(left_input.get_value())
            self.right_click_amount = int(right_input.get_value())
            self.storage.save_state(
                self.calories,
                self.left_click_amount,
                self.right_click_amount,
                self.session_start,
            )
            self.refresh_icon()
        dialog.destroy()

    def show_text_dialog(self, title, text):
        """Show read-only scrollable text in a modal dialog."""
        dialog = Gtk.Dialog(
            title=title,
            parent=None,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_size(640, 480)

        content = dialog.get_content_area()
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        text_view.get_buffer().set_text(text)

        scroller.add(text_view)
        content.add(scroller)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def show_error_dialog(self, title, message):
        """Show a modal error dialog with a short message."""
        dialog = Gtk.MessageDialog(
            None,
            Gtk.DialogFlags.MODAL,
            Gtk.MessageType.ERROR,
            Gtk.ButtonsType.CLOSE,
            title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def show_last_week_dialog(self, summary):
        """Show the weekly summary with a compact per-day bar graph."""
        dialog = Gtk.Dialog(
            title='Last 7 Days',
            parent=None,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_size(720, 560)

        content = dialog.get_content_area()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
        content.add(outer)

        session_started = self.session_start.strftime('%Y-%m-%d %H:%M')
        session_label = Gtk.Label(
            label=f'Active session: {self.calories} kcal (started {session_started})'
        )
        session_label.set_halign(Gtk.Align.START)
        outer.pack_start(session_label, False, False, 0)

        drawing_area = Gtk.DrawingArea()
        drawing_area.set_size_request(-1, 240)
        drawing_area.connect(
            'draw',
            self.draw_last_week_graph,
            summary['daily_bars'],
        )
        outer.pack_start(drawing_area, False, False, 0)

        legend = Gtk.Label(label='Rainbow bars = net calories per tracked day')
        legend.set_halign(Gtk.Align.START)
        outer.pack_start(legend, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        text_view.get_buffer().set_text(summary['text'])

        scroller.add(text_view)
        outer.pack_start(scroller, True, True, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def draw_last_week_graph(self, widget, cr, daily_bars):
        """Draw per-day net calories as rainbow vertical bars."""
        allocation = widget.get_allocation()
        width = allocation.width
        height = allocation.height

        # Match the app's dark visual style used in tray icons.
        cr.set_source_rgb(0.08, 0.09, 0.12)
        cr.paint()

        left = 50
        right = 14
        top = 14
        bottom = 30
        plot_width = max(1, width - left - right)
        plot_height = max(1, height - top - bottom)

        # Plot area border.
        cr.set_source_rgb(0.25, 0.27, 0.33)
        cr.rectangle(left, top, plot_width, plot_height)
        cr.stroke()

        # Subtle horizontal guide lines for readability.
        cr.set_source_rgb(0.18, 0.20, 0.25)
        cr.set_line_width(1.0)
        for idx in range(1, 4):
            y = top + (plot_height * idx / 4.0)
            cr.move_to(left, y)
            cr.line_to(left + plot_width, y)
        cr.stroke()

        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        cr.set_source_rgb(0.82, 0.85, 0.90)

        if not daily_bars:
            cr.move_to(left + 8, top + 18)
            cr.show_text('No tracked calorie data in the last 7 days.')
            return False

        values_for_scale = [0]
        for item in daily_bars:
            try:
                values_for_scale.append(int(item.get('net', 0)))
            except (TypeError, ValueError):
                values_for_scale.append(0)

        min_y = min(0, min(values_for_scale))
        max_y = max(values_for_scale)
        if max_y <= min_y:
            max_y = min_y + 1

        y_span = float(max_y - min_y)

        def y_for(value):
            return top + plot_height - ((value - min_y) / y_span) * plot_height

        zero_y = y_for(0)
        cr.set_source_rgb(0.55, 0.58, 0.64)
        cr.set_line_width(1.1)
        cr.move_to(left, zero_y)
        cr.line_to(left + plot_width, zero_y)
        cr.stroke()

        rainbow = [
            (0.90, 0.20, 0.20),
            (0.95, 0.50, 0.15),
            (0.95, 0.82, 0.20),
            (0.20, 0.78, 0.28),
            (0.20, 0.62, 0.95),
            (0.46, 0.36, 0.88),
            (0.88, 0.35, 0.75),
        ]

        count = max(1, len(daily_bars))
        slot = plot_width / float(count)
        bar_width = min(38.0, max(8.0, slot * 0.72))

        for idx, item in enumerate(daily_bars):
            try:
                value = int(item.get('net', 0))
            except (TypeError, ValueError):
                value = 0
            x = left + (idx * slot) + ((slot - bar_width) / 2.0)
            y_value = y_for(value)
            y_top = min(zero_y, y_value)
            bar_height = max(1.0, abs(y_value - zero_y))
            r, g, b = rainbow[idx % len(rainbow)]
            cr.set_source_rgb(r, g, b)
            cr.rectangle(x, y_top, bar_width, bar_height)
            cr.fill()

            label = item.get('label', '')
            cr.set_source_rgb(0.82, 0.85, 0.90)
            ext = cr.text_extents(label)
            lx = x + (bar_width - ext.width) / 2.0 - ext.x_bearing
            ly = height - 10
            cr.move_to(lx, ly)
            cr.show_text(label)

        cr.set_source_rgb(0.82, 0.85, 0.90)
        cr.move_to(8, top + 10)
        cr.show_text(f'{max_y} kcal')
        cr.move_to(8, zero_y)
        cr.show_text('0')
        cr.move_to(8, top + plot_height)
        cr.show_text(f'{min_y} kcal')
        return False

    def pixbuf_from_surface(self, surface, width, height):
        """Convert a Cairo surface into a GdkPixbuf with owned bytes."""
        data = bytes(surface.get_data())
        gbytes = GLib.Bytes.new(data)
        return GdkPixbuf.Pixbuf.new_from_bytes(
            gbytes,
            GdkPixbuf.Colorspace.RGB,
            True,
            8,
            width,
            height,
            surface.get_stride(),
        )

def main():
    """Start the calorie tray application."""
    CalorieTray()
    Gtk.main()


if __name__ == '__main__':
    main()
