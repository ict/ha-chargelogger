"""Tests for the add_charge service action."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.chargelogger.const import DOMAIN

from .conftest import BASE, CAR_A

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker


def _charge_posts(api: AiohttpClientMocker) -> list[dict]:
    return [call[2] for call in api.mock_calls if call[0] == 'POST' and str(call[1]).endswith('/charge/')]


async def _call(hass: HomeAssistant, *, response: bool = False, **data):
    return await hass.services.async_call(DOMAIN, 'add_charge', data, blocking=True, return_response=response)


async def test_service_registered(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert hass.services.has_service(DOMAIN, 'add_charge')


async def test_minimal_charge_uses_cpo_default_price(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    await _call(hass, car_id=CAR_A, cpo='home wallbox', kwh=32.5, km_driven=210)
    (body,) = _charge_posts(api)
    assert body['cpo_id'] == 'cpo-home'
    assert body['kwh_charged'] == 3250
    assert body['charge_type'] == 'AC'
    assert body['car_km_driven'] == 210
    assert 'car_odometer' not in body
    assert 'price_total' not in body
    assert body['date'][-6] in '+-'


async def test_full_charge_by_cpo_id(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _call(
        hass,
        car_id=CAR_A,
        cpo='cpo-fast',
        kwh=40,
        charge_type='DC',
        odometer=48250,
        price_total=23.6,
        soc_after=80,
        note='road trip',
        date='2026-10-09 18:30:00',
    )
    (body,) = _charge_posts(api)
    assert body['cpo_id'] == 'cpo-fast'
    assert body['charge_type'] == 'DC'
    assert body['car_odometer'] == 48250
    assert 'car_km_driven' not in body
    assert body['price_total'] == 2360
    assert body['car_soc_after'] == 80
    assert body['note'] == 'road trip'
    assert body['date'].startswith('2026-10-09T18:30:00')


async def test_returns_stored_charge(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    result = await _call(hass, response=True, car_id=CAR_A, cpo='Home Wallbox', kwh=32.5, odometer=48250)
    assert result == {
        'id': 'charge-1',
        'cpo_name': 'Home Wallbox',
        'kwh_charged': 32.5,
        'price_total': 9.75,
        'price_per_kwh': 0.3,
        'car_odometer': 48250,
    }


async def test_distance_required(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    with pytest.raises(Exception, match=r'odometer|km_driven'):
        await _call(hass, car_id=CAR_A, cpo='Home Wallbox', kwh=10)
    assert not _charge_posts(api)


async def test_odometer_and_km_driven_exclusive(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    with pytest.raises(Exception, match='not both'):
        await _call(hass, car_id=CAR_A, cpo='Home Wallbox', kwh=10, odometer=100, km_driven=10)


async def test_unknown_cpo(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    with pytest.raises(ServiceValidationError, match='Nowhere'):
        await _call(hass, car_id=CAR_A, cpo='Nowhere', kwh=10, km_driven=5)
    assert not _charge_posts(api)


async def test_unknown_car(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    with pytest.raises(ServiceValidationError, match='No car'):
        await _call(hass, car_id='nope', cpo='Home Wallbox', kwh=10, km_driven=5)
    assert not _charge_posts(api)


async def test_backend_rejection_shows_detail(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    api.clear_requests()
    api.get(f'{BASE}/cpo/', json=[{'id': 'cpo-home', 'name': 'Home Wallbox', 'default_price': 30}])
    api.post(f'{BASE}/charge/', status=422, json={'detail': 'Odometer must not decrease'})
    with pytest.raises(HomeAssistantError, match='Odometer must not decrease'):
        await _call(hass, car_id=CAR_A, cpo='Home Wallbox', kwh=10, odometer=1)


async def test_cpo_beyond_first_api_page(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    """The API returns 20 items by default; the integration must ask for all of them."""
    api.clear_requests()
    many = [{'id': f'cpo-{i}', 'name': f'Network {i}', 'default_price': 40} for i in range(32)]
    api.get(f'{BASE}/cpo/?limit=500', json=many)
    api.get(f'{BASE}/cpo/', json=many[:20])  # what a request without limit would get
    api.post(f'{BASE}/charge/', status=201, json={'id': 'c'})
    api.get(f'{BASE}/car/', json=[{'id': CAR_A, 'name': 'Alpha', 'sale_date': None}])
    api.get(f'{BASE}/charge/stats', json={'total': {}, 'per_car': []})
    api.get(f'{BASE}/expense/', json=[])
    await _call(hass, car_id=CAR_A, cpo='Network 31', kwh=10, km_driven=5)
    (body,) = _charge_posts(api)
    assert body['cpo_id'] == 'cpo-31'
