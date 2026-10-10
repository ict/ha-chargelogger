"""Diagnostics support."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_TOKEN, CONF_URL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ChargeloggerConfigEntry

TO_REDACT = {CONF_TOKEN, CONF_URL}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ChargeloggerConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry (token and URL redacted)."""
    data = entry.runtime_data.data
    return {
        'entry': async_redact_data(dict(entry.data), TO_REDACT),
        'options': dict(entry.options),
        'presets': [dict(sub.data) | {'title': sub.title} for sub in entry.subentries.values()],
        'data': {
            'month_start': data.month_start.isoformat(),
            'cars': [asdict(car) for car in data.cars.values()],
            'total': asdict(data.total),
            'per_car': {car_id: asdict(stats) for car_id, stats in data.per_car.items()},
        },
    }
