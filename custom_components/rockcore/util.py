"""🧰 Small helpers shared by the Rockcore Solar (RC-C) integration."""

from __future__ import annotations

from homeassistant.util import dt as dt_util


def timezone_offset_hours() -> float:
    """🕒 Return the local UTC offset in hours, the way the RC-C app sends it.

    ``dt_util.now()`` already resolves to the timezone configured in Home
    Assistant, so this needs nothing from ``hass``. It is evaluated on every
    request, so a daylight saving change is picked up without a reload.
    """
    offset = dt_util.now().utcoffset()
    if offset is None:
        return 0
    return round(offset.total_seconds() / 3600, 2)
