"""Sensor and coordinator tests."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.chargelogger.const import SCAN_INTERVAL

from .conftest import BASE, CAR_B, CAR_OLD

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker


def _state(hass: HomeAssistant, entry: MockConfigEntry, scope: str, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id('sensor', 'chargelogger', f'{entry.entry_id}_{scope}_{key}')
    assert entity_id, f'no entity for {scope}_{key}'
    return hass.states.get(entity_id)


async def test_total_values_converted(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert _state(hass, setup, 'total', 'energy').state == '45.67'
    assert _state(hass, setup, 'total', 'cost').state == '12.34'
    assert _state(hass, setup, 'total', 'count').state == '3'


async def test_car_values(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert _state(hass, setup, 'car-a', 'energy').state == '40.0'
    assert _state(hass, setup, 'car-a', 'cost').state == '10.0'
    assert _state(hass, setup, 'car-a', 'count').state == '2'


async def test_car_without_charges_is_zero(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert _state(hass, setup, CAR_B, 'energy').state == '0.0'
    assert _state(hass, setup, CAR_B, 'count').state == '0'


async def test_retired_car_has_no_entities(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    assert registry.async_get_entity_id('sensor', 'chargelogger', f'{setup.entry_id}_{CAR_OLD}_energy') is None


async def test_cost_unit_and_attributes(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    state = _state(hass, setup, 'total', 'cost')
    assert state.attributes['unit_of_measurement'] == 'EUR'
    assert state.attributes['device_class'] == 'monetary'
    assert state.attributes['state_class'] == 'total'
    assert state.attributes['charges_without_price'] == 1


async def test_energy_attributes(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    state = _state(hass, setup, 'total', 'energy')
    assert state.attributes['unit_of_measurement'] == 'kWh'
    assert state.attributes['device_class'] == 'energy'
    assert state.attributes['state_class'] == 'total'


async def test_last_reset_is_start_of_month_in_ha_timezone(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    state = _state(hass, setup, 'total', 'energy')
    expected = dt_util.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    assert dt_util.parse_datetime(state.attributes['last_reset']) == expected
    # The stats request carries the same tz-aware lower bound.
    stats_calls = [call for call in api.mock_calls if call[1].path == '/api/charge/stats']
    assert stats_calls[0][1].query['from_date'] == expected.isoformat()


async def test_devices_per_car_and_account(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), setup.entry_id)
    account = next(device for device in devices if device.name == 'Chargelogger (tester)')
    assert all(d.via_device_id == account.id for d in devices if d is not account)
    assert {device.name for device in devices} == {'Chargelogger (tester)', 'Alpha', 'Beta', 'Garage fee'}


async def test_update_refreshes_values(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker, freezer: FrozenDateTimeFactory
) -> None:
    api.clear_requests()
    api.get(f'{BASE}/users/me', json={'username': 'tester'})
    api.get(f'{BASE}/car/', json=[{'id': 'car-a', 'name': 'Alpha', 'sale_date': None}])
    api.get(f'{BASE}/expense/', json=[])
    api.get(
        f'{BASE}/charge/stats',
        json={'total': {'count': 9, 'kwh_charged': 100, 'price_total': 50, 'charges_without_price': 0}, 'per_car': []},
    )
    freezer.tick(SCAN_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _state(hass, setup, 'total', 'count').state == '9'
    # car-b vanished -> its sensors become unavailable
    assert _state(hass, setup, CAR_B, 'count').state == 'unavailable'


@pytest.mark.parametrize(
    ('status', 'expected'),
    [(500, ConfigEntryState.SETUP_RETRY), (401, ConfigEntryState.SETUP_ERROR)],
)
async def test_setup_failures(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker, status: int, expected
) -> None:
    aioclient_mock.get(f'{BASE}/car/', status=status)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is expected


async def test_new_car_gets_entities_on_update(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    api.clear_requests()
    api.get(f'{BASE}/car/', json=[{'id': 'car-new', 'name': 'Gamma', 'sale_date': None}])
    api.get(f'{BASE}/expense/', json=[])
    api.get(
        f'{BASE}/charge/stats',
        json={'total': {'count': 0, 'kwh_charged': 0, 'price_total': 0, 'charges_without_price': 0}, 'per_car': []},
    )
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, setup, 'car-new', 'count').state == '0'
