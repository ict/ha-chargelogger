"""Service actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORIES,
    CHARGE_TYPES,
    CONF_AMOUNT,
    CONF_CAR,
    CONF_CAR_ID,
    CONF_CATEGORY,
    CONF_CHARGE_TYPE,
    CONF_CONFIG_ENTRY_ID,
    CONF_CPO,
    CONF_DATE,
    CONF_KIND,
    CONF_KM_DRIVEN,
    CONF_KWH,
    CONF_NOTE,
    CONF_ODOMETER,
    CONF_PRICE_TOTAL,
    CONF_SOC_AFTER,
    DOMAIN,
    KINDS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .coordinator import ChargeloggerConfigEntry

SERVICE_ADD_EXPENSE = 'add_expense'
SERVICE_ADD_CHARGE = 'add_charge'

# `car` takes a car device id, a car name or a Chargelogger car id; `car_id` is the original field name.
CAR_FIELDS = {
    probatio.Exclusive(CONF_CAR, 'car', msg='give either car or car_id, not both'): cv.string,
    probatio.Exclusive(CONF_CAR_ID, 'car', msg='give either car or car_id, not both'): cv.string,
}

ADD_EXPENSE_SCHEMA = probatio.All(
    probatio.Schema(
        {
            probatio.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
            **CAR_FIELDS,
            probatio.Required(CONF_CATEGORY): probatio.In(CATEGORIES),
            probatio.Required(CONF_AMOUNT): probatio.All(probatio.Coerce(float), probatio.Range(min=0.01)),
            probatio.Optional(CONF_KIND, default='expense'): probatio.In(KINDS),
            probatio.Optional(CONF_NOTE): cv.string,
            probatio.Optional(CONF_DATE): cv.datetime,
        }
    ),
    cv.has_at_least_one_key(CONF_CAR, CONF_CAR_ID),
)


DISTANCE_MSG = 'give either odometer or km_driven, not both'

ADD_CHARGE_SCHEMA = probatio.All(
    probatio.Schema(
        {
            probatio.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
            **CAR_FIELDS,
            probatio.Required(CONF_CPO): cv.string,
            probatio.Required(CONF_KWH): probatio.All(probatio.Coerce(float), probatio.Range(min=0.01)),
            probatio.Optional(CONF_CHARGE_TYPE, default='AC'): probatio.In(CHARGE_TYPES),
            probatio.Exclusive(CONF_ODOMETER, 'distance', msg=DISTANCE_MSG): probatio.All(
                probatio.Coerce(int), probatio.Range(min=0)
            ),
            probatio.Exclusive(CONF_KM_DRIVEN, 'distance', msg=DISTANCE_MSG): probatio.All(
                probatio.Coerce(int), probatio.Range(min=0)
            ),
            probatio.Optional(CONF_PRICE_TOTAL): probatio.All(probatio.Coerce(float), probatio.Range(min=0)),
            probatio.Optional(CONF_SOC_AFTER): probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=100)),
            probatio.Optional(CONF_NOTE): cv.string,
            probatio.Optional(CONF_DATE): cv.datetime,
        }
    ),
    cv.has_at_least_one_key(CONF_ODOMETER, CONF_KM_DRIVEN),
    cv.has_at_least_one_key(CONF_CAR, CONF_CAR_ID),
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


def _resolve_car(hass: HomeAssistant, call: ServiceCall) -> tuple[ChargeloggerConfigEntry, str]:
    """Find the account and Chargelogger car id for the call's `car` / `car_id` value."""
    value = str(call.data.get(CONF_CAR) or call.data[CONF_CAR_ID]).strip()
    entry_id = call.data.get(CONF_CONFIG_ENTRY_ID)

    # A car device (what the UI's device picker sends) identifies account and car at once.
    if device := dr.async_get(hass).async_get(value):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            for entry_key in device.config_entries:
                prefix = f'{entry_key}_'
                if identifier.startswith(prefix) and identifier[len(prefix) :] in _loaded_cars(hass, entry_key):
                    return _resolve_entry(hass, entry_key), identifier[len(prefix) :]
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key='not_a_car_device')

    if entry_id is not None:
        entries = [_resolve_entry(hass, entry_id)]
    else:
        entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key='entry_not_loaded')
    by_id = [(e, value) for e in entries if value in e.runtime_data.data.cars]
    by_name = [
        (e, car_id)
        for e in entries
        for car_id, car in e.runtime_data.data.cars.items()
        if car.name.casefold() == value.casefold()
    ]
    matches = by_id or by_name
    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key='unknown_car', translation_placeholders={'car_id': value}
        )
    if len(matches) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key='ambiguous_car', translation_placeholders={'car': value}
        )
    return matches[0]


def _loaded_cars(hass: HomeAssistant, entry_id: str) -> dict:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return {}
    return entry.runtime_data.data.cars


async def _async_add_expense(call: ServiceCall) -> None:
    """Handle chargelogger.add_expense."""
    hass = call.hass
    entry, car_id = _resolve_car(hass, call)
    coordinator = entry.runtime_data
    date = _local_date(call)
    await coordinator.async_create_expense(
        car_id=car_id,
        category=call.data[CONF_CATEGORY],
        kind=call.data[CONF_KIND],
        amount_cents=round(call.data[CONF_AMOUNT] * 100),
        note=call.data.get(CONF_NOTE),
        date=date,
    )


def _local_date(call: ServiceCall):
    """Return the call's optional date, treating a naive value as HA local time."""
    date = call.data.get(CONF_DATE)
    if date is not None and date.tzinfo is None:
        date = date.replace(tzinfo=dt_util.get_default_time_zone())
    return date


async def _async_add_charge(call: ServiceCall) -> ServiceResponse:
    """Handle chargelogger.add_charge."""
    entry, car_id = _resolve_car(call.hass, call)
    coordinator = entry.runtime_data
    # CPO by id or (case-insensitive) name, so automations can say "Home Wallbox".
    wanted = call.data[CONF_CPO].strip()
    cpos = await coordinator.async_get_cpos()
    cpo = next((c for c in cpos if str(c['id']) == wanted), None) or next(
        (c for c in cpos if str(c['name']).casefold() == wanted.casefold()), None
    )
    if cpo is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key='unknown_cpo', translation_placeholders={'cpo': wanted}
        )
    body: dict[str, Any] = {
        'date': (_local_date(call) or dt_util.now()).isoformat(),
        'car_id': car_id,
        'cpo_id': str(cpo['id']),
        'kwh_charged': round(call.data[CONF_KWH] * 100),
        'charge_type': call.data[CONF_CHARGE_TYPE],
    }
    if CONF_ODOMETER in call.data:
        body['car_odometer'] = call.data[CONF_ODOMETER]
    else:
        body['car_km_driven'] = call.data[CONF_KM_DRIVEN]
    if CONF_PRICE_TOTAL in call.data:  # otherwise the backend uses the CPO's default price
        body['price_total'] = round(call.data[CONF_PRICE_TOTAL] * 100)
    if CONF_SOC_AFTER in call.data:
        body['car_soc_after'] = call.data[CONF_SOC_AFTER]
    if note := call.data.get(CONF_NOTE):
        body['note'] = note
    charge = await coordinator.async_create_charge(body)
    if not call.return_response:
        return None
    return {
        'id': charge.get('id'),
        'cpo_name': charge.get('cpo_name'),
        'kwh_charged': charge.get('kwh_charged', 0) / 100,
        'price_total': (charge.get('price_total') or 0) / 100,
        'price_per_kwh': (charge.get('price_per_kwh') or 0) / 100,
        'car_odometer': charge.get('car_odometer'),
    }


def async_setup_services(hass: HomeAssistant) -> None:
    """Register service actions."""
    hass.services.async_register(DOMAIN, SERVICE_ADD_EXPENSE, _async_add_expense, schema=ADD_EXPENSE_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CHARGE,
        _async_add_charge,
        schema=ADD_CHARGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
