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

/* Room panels */
.panel {
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 1;
    padding: 1 2;
    height: auto;
}
#room-tabs {
    height: 1fr;
}
#tab-schedule {
    padding: 0;
}
#tab-energy {
    overflow-y: auto;
}

"""
