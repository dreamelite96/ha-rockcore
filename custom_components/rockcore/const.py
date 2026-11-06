"""📌 Constants for the Rockcore Solar (RC-C) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

# ─────────────────────────────────────────────────────────────────────────────
# 🏷️ Identity
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN: Final = "rockcore"

MANUFACTURER: Final = "Rockcore"

# ─────────────────────────────────────────────────────────────────────────────
# ⏱️ Polling
# ─────────────────────────────────────────────────────────────────────────────

CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=60)
#: Bounds (in seconds) offered by the options flow.
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 900

# ─────────────────────────────────────────────────────────────────────────────
# 🌐 Cloud API
# ─────────────────────────────────────────────────────────────────────────────

#: Base URL of the cloud used by the RC-C mobile app (JowoIoT platform, OEM "rc").
API_BASE: Final = "https://app.rc-ess.com/jowoiot-proxy/api/project/rc"

#: The RC-C app identifies itself with these OEM/scope headers. They are not
#: strictly required by the backend, but we mirror the app to stay compatible.
API_OEM: Final = "rc"
API_SCOPE: Final = "yx_test"

#: Total timeout of a single HTTP request, in seconds.
REQUEST_TIMEOUT: Final = 30

# ─────────────────────────────────────────────────────────────────────────────
# 🚨 Alarms
# ─────────────────────────────────────────────────────────────────────────────

#: Page size used when listing alarms. The backend rejects anything above 100
#: with ``400 / "request param invalid"``.
ALARM_PAGE_SIZE: Final = 100

#: 🛡️ Safety net so a pathological account cannot spin through endless pages.
#: 10 pages of 100 covers a 7-day history of a large plant on a stormy week.
ALARM_MAX_PAGES: Final = 10

#: How far back the isolation analysis looks. Long enough for recurrence to
#: mean something, short enough that a unit repaired last week stops counting.
ALARM_HISTORY_DAYS: Final = 7

#: 🐢 The 7-day alarm history is by far the heaviest call of a poll and it only
#: moves slowly, so it is refreshed on its own, longer interval.
ALARM_HISTORY_REFRESH: Final = timedelta(minutes=15)

#: Two alarms of the same kind this close together share a cause. Measured on
#: the reference plant: grid events reach every inverter within a few seconds,
#: so anything wider only makes the filter more conservative.
ALARM_COINCIDENCE_WINDOW: Final = timedelta(seconds=120)

#: A unit has to reoffend on ``ALARM_RECENT_DAYS_MIN`` of the last
#: ``ALARM_RECENT_DAYS`` days before it is flagged. That is what separates a
#: developing fault from the one-off blip every inverter produces now and then.
ALARM_RECENT_DAYS: Final = 3
ALARM_RECENT_DAYS_MIN: Final = 2

#: 📏 Home Assistant drops the state attributes of an entity above 16 KB, so the
#: list of open alarms exposed as an attribute is capped. The counts stay exact.
MAX_ALARMS_IN_ATTRIBUTES: Final = 25
