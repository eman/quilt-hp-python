"""Application stylesheet."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────

_APP_CSS = """
Screen {
    background: $surface;
}

/* Loading */
#loading-container {
    align: center middle;
    height: 100%;
}
#loading-label {
    margin-top: 2;
    text-align: center;
    color: $text-muted;
}

/* Boot error */
#boot-error-container {
    align: center middle;
    height: 100%;
}
#boot-error-title {
    text-style: bold;
    color: $error;
    text-align: center;
}
#boot-error-message {
    margin-top: 1;
    text-align: center;
}
#boot-error-hint {
    margin-top: 2;
    text-align: center;
    color: $text-muted;
}

/* OTP modal */
OtpScreen {
    align: center middle;
}
#otp-dialog {
    width: 60;
    height: auto;
    border: round $primary;
    padding: 1 2;
    background: $surface;
}
#otp-label {
    margin-bottom: 1;
}

/* Dashboard */
#dashboard-list {
    height: 1fr;
    border: round $primary-darken-2;
    margin: 1 2;
}
#dashboard-statusbar {
    height: 1;
    padding: 0 2;
    background: $primary-darken-3;
    color: $text-muted;
    dock: bottom;
}

/* Room panels */
.panel {
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 1;
    padding: 1 2;
    height: auto;
}
.section-label {
    text-style: bold;
    color: $accent;
    margin-top: 1;
}
.kv-key {
    color: $text-muted;
    width: 22;
}
.kv-val {
    color: $text;
}
.section-rule {
    margin: 1 0;
}
#room-tabs {
    height: 1fr;
}
#tab-status {
    overflow-y: auto;
}
#tab-perf {
    padding: 0;
}
#tab-schedule {
    padding: 0;
}
.sched-row {
    height: 1fr;
}
.sched-days-panel {
    width: 22;
    height: 1fr;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 0 0 1;
    padding: 0 1;
}
.sched-events-panel {
    width: 1fr;
    height: 1fr;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 1 0 0;
    padding: 0 1;
}
#sched-status {
    height: 1;
    padding: 0 2;
    background: $surface-darken-1;
    color: $text-muted;
}
#tab-energy {
    overflow-y: auto;
}
.energy-summary {
    height: auto;
    padding: 1 2;
    margin: 0 1;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
}
.energy-chart {
    height: auto;
    padding: 1 2;
    margin: 0 1;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
}
#energy-status {
    padding: 0 2;
    color: $text-muted;
}
.controls-sensors-row {
    height: auto;
}
.controls-panel {
    width: 1fr;
}
.sensors-panel {
    width: 1fr;
}
.dial-panel {
    width: 1fr;
    height: auto;
}
.qsm-panel {
    width: 1fr;
    height: auto;
}
.perf-row {
    height: 1fr;
}
.perf-left {
    width: 1fr;
    height: 1fr;
}
.perf-right {
    width: 1fr;
    height: 1fr;
}

/* System screen */
#system-container {
    overflow-y: auto;
    padding: 1 2;
}
.odu-panel {
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
#odu-row {
    height: auto;
    margin-bottom: 1;
}
#odu-row .odu-panel {
    width: 1fr;
    margin-bottom: 0;
    margin-right: 1;
}
"""
