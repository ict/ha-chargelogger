"""Sensors for Chargelogger: monthly energy, cost and charge count per account and car."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy

from .api import Stats
from .const import CONF_CURRENCY, DEFAULT_CURRENCY
from .entity import ChargeloggerEntity, account_device, car_device

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import ChargeloggerConfigEntry, ChargeloggerCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ChargeloggerSensorDescription(SensorEntityDescription):
    """Describes a Chargelogger sensor."""

    value_fn: Callable[[Stats], float | int]


SENSORS: tuple[ChargeloggerSensorDescription, ...] = (
    ChargeloggerSensorDescription(
        key='energy',
        translation_key='energy',
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.energy_kwh,
    ),
    ChargeloggerSensorDescription(
        key='cost',
        translation_key='cost',
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.cost,
    ),
    ChargeloggerSensorDescription(
        key='count',
        translation_key='count',
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda stats: stats.count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ChargeloggerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up sensors; cars that appear later get entities on the next update."""
    coordinator = entry.runtime_data
    known: set[str | None] = set()

    def _add_missing() -> None:
        new: list[ChargeloggerSensor] = []
        scopes: list[str | None] = [None, *coordinator.data.active_cars]
        for scope in scopes:
            if scope in known:
                continue
            known.add(scope)
            new.extend(ChargeloggerSensor(coordinator, entry, description, scope) for description in SENSORS)
        if new:
            async_add_entities(new)

    _add_missing()
    entry.async_on_unload(coordinator.async_add_listener(_add_missing))


class ChargeloggerSensor(ChargeloggerEntity, SensorEntity):
    """Statistic for the current month, for the whole account (car_id None) or a single car."""

    entity_description: ChargeloggerSensorDescription

    def __init__(
        self,
        coordinator: ChargeloggerCoordinator,
        entry: ChargeloggerConfigEntry,
        description: ChargeloggerSensorDescription,
        car_id: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._car_id = car_id
        scope = 'total' if car_id is None else car_id
        self._attr_unique_id = f'{entry.entry_id}_{scope}_{description.key}'
        self._attr_device_info = self._build_device(entry)
        if description.key == 'cost':
            self._attr_native_unit_of_measurement = entry.options.get(CONF_CURRENCY, DEFAULT_CURRENCY)

    def _build_device(self, entry: ChargeloggerConfigEntry) -> DeviceInfo:
        if self._car_id is None:
            return account_device(entry.entry_id, entry.title)
        return car_device(
            entry.entry_id,
            self.coordinator.account_device_id,
            self._car_id,
            self.coordinator.data.cars[self._car_id].name,
        )

    @property
    def _stats(self) -> Stats | None:
        data = self.coordinator.data
        if self._car_id is None:
            return data.total
        if self._car_id not in data.active_cars:
            return None
        return data.per_car.get(self._car_id, Stats())

    @property
    def available(self) -> bool:
        """Unavailable when the car is gone or retired."""
        return super().available and self._stats is not None

    @property
    def native_value(self) -> float | int | None:
        """Return the converted value."""
        stats = self._stats
        return None if stats is None else self.entity_description.value_fn(stats)

    @property
    def last_reset(self) -> datetime:
        """Start of the current month in the HA time zone."""
        return self.coordinator.data.month_start

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose how many charges lack a price (cost may be understated)."""
        stats = self._stats
        if self.entity_description.key != 'cost' or stats is None:
            return None
        return {'charges_without_price': stats.charges_without_price}
