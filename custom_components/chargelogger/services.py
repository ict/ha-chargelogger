"""Service actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORIES,
    CONF_AMOUNT,
    CONF_CAR_ID,
    CONF_CATEGORY,
    CONF_CONFIG_ENTRY_ID,
    CONF_DATE,
    CONF_KIND,
    CONF_NOTE,
    DOMAIN,
    KINDS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .coordinator import ChargeloggerConfigEntry

SERVICE_ADD_EXPENSE = 'add_expense'

ADD_EXPENSE_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        probatio.Required(CONF_CAR_ID): cv.string,
        probatio.Required(CONF_CATEGORY): probatio.In(CATEGORIES),
        probatio.Required(CONF_AMOUNT): probatio.All(probatio.Coerce(float), probatio.Range(min=0.01)),
        probatio.Optional(CONF_KIND, default='expense'): probatio.In(KINDS),
        probatio.Optional(CONF_NOTE): cv.string,
        probatio.Optional(CONF_DATE): cv.datetime,
    }
)


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ChargeloggerConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id is None:
        if len(entries) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key='entry_id_required')
        entry = entries[0]
    else:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key='entry_not_found', translation_placeholders={'id': entry_id}
            )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key='entry_not_loaded')
    return entry


async def _async_add_expense(call: ServiceCall) -> None:
    """Handle chargelogger.add_expense."""
    hass = call.hass
    entry = _resolve_entry(hass, call.data.get(CONF_CONFIG_ENTRY_ID))
    coordinator = entry.runtime_data
    car_id = call.data[CONF_CAR_ID]
    car = coordinator.data.cars.get(car_id)
    if car is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key='unknown_car', translation_placeholders={'car_id': car_id}
        )
    date = call.data.get(CONF_DATE)
    if date is not None and date.tzinfo is None:
        date = date.replace(tzinfo=dt_util.get_default_time_zone())
    await coordinator.async_create_expense(
        car_id=car_id,
        category=call.data[CONF_CATEGORY],
        kind=call.data[CONF_KIND],
        amount_cents=round(call.data[CONF_AMOUNT] * 100),
        note=call.data.get(CONF_NOTE),
        date=date,
    )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register service actions."""
    hass.services.async_register(DOMAIN, SERVICE_ADD_EXPENSE, _async_add_expense, schema=ADD_EXPENSE_SCHEMA)
