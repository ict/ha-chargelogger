"""Sensors for Chargelogger: this month's charging and expenses, and the last car wash, per account and car."""

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

from .const import CONF_CURRENCY, DEFAULT_CURRENCY
from .entity import ChargeloggerEntity, account_device, car_device

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import ChargeloggerConfigEntry, ChargeloggerCoordinator, ScopeData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ChargeloggerSensorDescription(SensorEntityDescription):
    """Describes a Chargelogger sensor."""

    value_fn: Callable[[ScopeData], float | int | datetime | None]
    attrs_fn: Callable[[ScopeData], dict[str, Any]] | None = None
    monetary: bool = False


SENSORS: tuple[ChargeloggerSensorDescription, ...] = (
    ChargeloggerSensorDescription(
        key='energy',
        translation_key='energy',
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d: d.charges.energy_kwh,
    ),
    ChargeloggerSensorDescription(
        key='cost',
        translation_key='cost',
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        monetary=True,
        value_fn=lambda d: d.charges.cost,
        attrs_fn=lambda d: {'charges_without_price': d.charges.charges_without_price},
    ),
    ChargeloggerSensorDescription(
        key='count',
        translation_key='count',
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.charges.count,
    ),
    ChargeloggerSensorDescription(
        key='expenses',
        translation_key='expenses',
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        monetary=True,
        value_fn=lambda d: d.expenses.net,
        attrs_fn=lambda d: {
            'expenses': d.expenses.expenses,
            'income': d.expenses.income,
            'entries': d.expenses.count,
            **{f'category_{name}': amount for name, amount in d.expenses.per_category.items()},
        },
    ),
    ChargeloggerSensorDescription(
        key='last_wash',
        translation_key='last_wash',
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.last_wash,
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
        if description.monetary:
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
    def _scope(self) -> ScopeData | None:
        return self.coordinator.data.scope(self._car_id)

    @property
    def available(self) -> bool:
        """Unavailable when the car is gone or retired."""
        return super().available and self._scope is not None

    @property
    def native_value(self) -> float | int | datetime | None:
        """Return the converted value."""
        scope = self._scope
        return None if scope is None else self.entity_description.value_fn(scope)

    @property
    def last_reset(self) -> datetime | None:
        """Start of the current month in the HA time zone, for the monthly totals."""
        if self.entity_description.state_class is not SensorStateClass.TOTAL:
            return None
        return self.coordinator.data.month_start

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Breakdowns, e.g. charges without a price or expenses per category."""
        scope = self._scope
        if self.entity_description.attrs_fn is None or scope is None:
            return None
        return self.entity_description.attrs_fn(scope)
