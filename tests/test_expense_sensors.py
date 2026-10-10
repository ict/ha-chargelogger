"""Monthly expense sensors and the (disabled by default) last car wash sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.chargelogger.api import ChargeloggerClient

from .conftest import BASE, CAR_A, CAR_B, CAR_OLD, TOKEN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, scope: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id('sensor', 'chargelogger', f'{entry.entry_id}_{scope}_{key}')


def _state(hass: HomeAssistant, entry: MockConfigEntry, scope: str, key: str):
    entity_id = _entity_id(hass, entry, scope, key)
    assert entity_id, f'no entity for {scope}_{key}'
    return hass.states.get(entity_id)


async def test_account_expenses_net_of_income(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    state = _state(hass, setup, 'total', 'expenses')
    # 16.90 + 4.50 + 80.00 (legacy entry without kind counts as expense) - 10.00 income
    assert state.state == '91.4'
    assert state.attributes['unit_of_measurement'] == 'EUR'
    assert state.attributes['expenses'] == 101.4
    assert state.attributes['income'] == 10.0
    assert state.attributes['entries'] == 4
    assert state.attributes['category_cleaning'] == 16.9
    assert state.attributes['category_tires'] == 80.0
    assert 'category_other' not in state.attributes  # income is not a cost category
    assert state.attributes['last_reset'].startswith(setup.runtime_data.data.month_start.isoformat()[:10])


async def test_per_car_expenses(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert _state(hass, setup, CAR_A, 'expenses').state == '21.4'
    assert _state(hass, setup, CAR_B, 'expenses').state == '70.0'
    assert _entity_id(hass, setup, CAR_OLD, 'expenses') is None


async def test_last_wash_disabled_by_default(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    entity_id = _entity_id(hass, setup, CAR_A, 'last_wash')
    assert entity_id is not None
    assert er.async_get(hass).async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id) is None


async def test_last_wash_when_enabled(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    for scope in ('total', CAR_A, CAR_B):
        registry.async_update_entity(_entity_id(hass, setup, scope, 'last_wash'), disabled_by=None)
    await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    car_a = _state(hass, setup, CAR_A, 'last_wash')
    assert car_a.state == '2026-10-04T09:30:00+00:00'
    assert car_a.attributes['device_class'] == 'timestamp'
    assert 'last_reset' not in car_a.attributes
    assert _state(hass, setup, 'total', 'last_wash').state == '2026-10-04T09:30:00+00:00'
    assert _state(hass, setup, CAR_B, 'last_wash').state == 'unknown'  # never washed


async def test_get_expenses_pages_through_results(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    item = {'id': 'x', 'car_id': CAR_A, 'category': 'other', 'amount': 1, 'date': '2026-10-01T00:00:00Z'}
    aioclient_mock.get(f'{BASE}/expense/?offset=0', json=[item] * 500)
    aioclient_mock.get(f'{BASE}/expense/?offset=500', json=[item] * 3)
    client = ChargeloggerClient(async_get_clientsession(hass), BASE, TOKEN)
    assert len(await client.get_expenses()) == 503
