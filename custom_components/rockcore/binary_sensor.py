"""🚦 Binary sensors for the Rockcore Solar (RC-C) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import MAX_ALARMS_IN_ATTRIBUTES
from .coordinator import InverterData, RockcoreConfigEntry, RockcoreCoordinator, StationData
from .entity import RockcoreInverterEntity, RockcoreStationEntity

# ─────────────────────────────────────────────────────────────────────────────
# 🔄 Value converters and attribute helpers
# ─────────────────────────────────────────────────────────────────────────────


def _as_bool(value: Any) -> bool | None:
    """Coerce the loosely typed API flags (bool, number, string) to a bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return None


def alarm_attributes(alarms: list[dict[str, Any]]) -> dict[str, Any]:
    """🚨 Summarise open alarms for the attribute dictionary of an entity.

    💡 The per-level counts are worth more than the plain total for automations.
    The cloud never clears some alarms (the "Channel N undervoltage" ones here
    have been open since commissioning), so this entity can sit at ``on``
    indefinitely. Trigger on a level count, or on the count changing, instead of
    on the state flipping.
    """
    levels: dict[str, int] = {}
    for alarm in alarms:
        level = alarm.get("alarmLevel")
        if level is not None:
            levels[f"level_{level}"] = levels.get(f"level_{level}", 0) + 1
    return {
        "active_alarm_count": len(alarms),
        "active_alarm_levels": levels,
        # 📏 Capped: oversized attributes are dropped by the recorder. The
        # counts above always cover every open alarm.
        "active_alarms": [
            {
                "message": alarm.get("message"),
                "level": alarm.get("alarmLevel"),
                "device": alarm.get("deviceName"),
                "since": _alarm_timestamp(alarm),
            }
            for alarm in alarms[:MAX_ALARMS_IN_ATTRIBUTES]
        ],
        "active_alarms_truncated": len(alarms) > MAX_ALARMS_IN_ATTRIBUTES,
    }


def _alarm_timestamp(alarm: dict[str, Any]) -> str | None:
    """🕒 Return an alarm time as ISO 8601 (the API sends millisecond epochs as strings)."""
    raw = alarm.get("time") or alarm.get("createTime")
    try:
        millis = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return dt_util.utc_from_timestamp(millis / 1000).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 🧩 Entity descriptions
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class RockcoreStationBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a plant-level binary sensor."""

    value_fn: Callable[[StationData], bool | None]
    attrs_fn: Callable[[StationData], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class RockcoreInverterBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an inverter-level binary sensor."""

    value_fn: Callable[[InverterData], bool | None]
    attrs_fn: Callable[[InverterData], dict[str, Any]] | None = None


#: ☀️ Binary sensors created once per plant.
STATION_BINARY_SENSORS: tuple[RockcoreStationBinarySensorDescription, ...] = (
    RockcoreStationBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda station: _as_bool(station.info.get("state")),
    ),
    RockcoreStationBinarySensorDescription(
        key="alarm",
        translation_key="alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        # 💡 Driven by the open-alarm list, not by the plant's own ``isAlarm``
        # flag: that flag stays false even with alarms open, so it never fired.
        value_fn=lambda station: bool(station.active_alarms),
        attrs_fn=lambda station: alarm_attributes(station.active_alarms),
    ),
)


#: 🔋 Binary sensors created once per microinverter.
INVERTER_BINARY_SENSORS: tuple[RockcoreInverterBinarySensorDescription, ...] = (
    RockcoreInverterBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda inv: _as_bool(
            inv.detail.get("isOnline", inv.summary.get("isOnline"))
        ),
    ),
    RockcoreInverterBinarySensorDescription(
        key="alarm",
        translation_key="alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda inv: bool(inv.active_alarms),
        attrs_fn=lambda inv: alarm_attributes(inv.active_alarms),
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# 🚀 Platform setup
# ─────────────────────────────────────────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RockcoreConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """🚀 Set up the Rockcore binary sensors, adding new ones as plants appear."""
    coordinator = entry.runtime_data
    #: unique ids already handed to Home Assistant, so nothing is added twice.
    known: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        entities: list[BinarySensorEntity] = []

        for station_id, station in (coordinator.data or {}).items():
            # ☀️ Plant-level binary sensors.
            for description in STATION_BINARY_SENSORS:
                if (uid := f"{station_id}_{description.key}") not in known:
                    known.add(uid)
                    entities.append(
                        RockcoreStationBinarySensor(coordinator, station_id, description)
                    )
            # 🔋 Inverter-level binary sensors.
            for org_id in station.inverters:
                for inverter_description in INVERTER_BINARY_SENSORS:
                    if (uid := f"{org_id}_{inverter_description.key}") not in known:
                        known.add(uid)
                        entities.append(
                            RockcoreInverterBinarySensor(
                                coordinator, station_id, org_id, inverter_description
                            )
                        )

        if entities:
            async_add_entities(entities)

    # Create what exists now, then keep watching every later poll.
    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


# ─────────────────────────────────────────────────────────────────────────────
# 🧱 Entities
# ─────────────────────────────────────────────────────────────────────────────


class RockcoreStationBinarySensor(RockcoreStationEntity, BinarySensorEntity):
    """☀️ A plant-level binary sensor."""

    entity_description: RockcoreStationBinarySensorDescription

    def __init__(
        self,
        coordinator: RockcoreCoordinator,
        station_id: str,
        description: RockcoreStationBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, station_id)
        self.entity_description = description
        self._attr_unique_id = f"{station_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.station)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the open alarms, when this sensor tracks them."""
        if self.entity_description.attrs_fn is None or not self.available:
            return None
        return self.entity_description.attrs_fn(self.station)


class RockcoreInverterBinarySensor(RockcoreInverterEntity, BinarySensorEntity):
    """🔋 An inverter-level binary sensor."""

    entity_description: RockcoreInverterBinarySensorDescription

    def __init__(
        self,
        coordinator: RockcoreCoordinator,
        station_id: str,
        org_id: str,
        description: RockcoreInverterBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, station_id, org_id)
        self.entity_description = description
        self._attr_unique_id = f"{org_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.inverter)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the open alarms, when this sensor tracks them."""
        if self.entity_description.attrs_fn is None or not self.available:
            return None
        return self.entity_description.attrs_fn(self.inverter)
