"""Quick-action buttons: one per user-defined preset (config subentry)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AMOUNT,
    CONF_CAR_ID,
    CONF_CATEGORY,
    CONF_KIND,
    CONF_NOTE,
    PRESS_GUARD_SECONDS,
    SUBENTRY_PRESET,
)
from .entity import ChargeloggerEntity, preset_device

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import ChargeloggerConfigEntry, ChargeloggerCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ChargeloggerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create one button per preset subentry."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_PRESET:
            continue
        async_add_entities([PresetButton(entry.runtime_data, entry, subentry)], config_subentry_id=subentry.subentry_id)


class PresetButton(ChargeloggerEntity, ButtonEntity):
    """Pressing this button books the preset as an expense dated now."""

    def __init__(
        self, coordinator: ChargeloggerCoordinator, entry: ChargeloggerConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._preset = dict(subentry.data)
        self._attr_name = None  # the entity is the device's main feature
        # Icon per category (icons.json); income presets share one icon. A user-set icon still wins.
        self._attr_translation_key = 'income' if self._preset[CONF_KIND] == 'income' else self._preset[CONF_CATEGORY]
        self._attr_unique_id = f'{entry.entry_id}_preset_{subentry.subentry_id}'
        self._last_press: datetime | None = None
        self._attr_device_info = preset_device(
            entry.entry_id, coordinator.account_device_id, subentry.subentry_id, subentry.title
        )

    @property
    def available(self) -> bool:
        """Unavailable while the preset's car is unknown or retired."""
        car = self.coordinator.data.cars.get(self._preset[CONF_CAR_ID])
        return super().available and car is not None and not car.retired

    async def async_press(self) -> None:
        """Create the expense, ignoring repeated presses within the guard window."""
        now = dt_util.utcnow()
        if self._last_press is not None and (now - self._last_press).total_seconds() < PRESS_GUARD_SECONDS:
            _LOGGER.warning('Ignoring repeated press of %s within %s seconds', self.entity_id, PRESS_GUARD_SECONDS)
            return
        self._last_press = now
        try:
            await self.coordinator.async_create_expense(
                car_id=self._preset[CONF_CAR_ID],
                category=self._preset[CONF_CATEGORY],
                kind=self._preset[CONF_KIND],
                amount_cents=int(self._preset[CONF_AMOUNT]),
                note=self._preset.get(CONF_NOTE),
            )
        except Exception:
            # A failed booking must not block an immediate retry.
            self._last_press = None
            raise
