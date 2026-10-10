"""Preset subentry management, buttons, press guard."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chargelogger.const import CONF_TOKEN, CONF_URL, DOMAIN, SUBENTRY_PRESET

from .conftest import BASE, CAR_A, CAR_OLD, TOKEN, preset

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

BUTTON = 'button.garage_fee'


def _posts(api: AiohttpClientMocker) -> list[dict]:
    return [call[2] for call in api.mock_calls if call[0] == 'POST']


async def _press(hass: HomeAssistant, entity_id: str = BUTTON) -> None:
    await hass.services.async_call(BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True)


async def test_button_created_for_preset(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    reg_entry = registry.async_get(BUTTON)
    assert reg_entry is not None
    assert reg_entry.config_subentry_id == next(iter(setup.subentries))


async def test_press_posts_expected_body(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    await _press(hass)
    (body,) = _posts(api)
    assert dt_util.parse_datetime(body.pop('date')) is not None
    assert body == {'car_id': CAR_A, 'category': 'tolls_parking', 'kind': 'expense', 'amount': 250, 'note': 'Garage'}


async def test_press_sends_bearer_header_and_tz_aware_date(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    await _press(hass)
    post = next(call for call in api.mock_calls if call[0] == 'POST')
    assert post[3]['Authorization'] == 'Bearer clk_test_secret_token'
    assert post[2]['date'][-6] in '+-'


async def test_press_refreshes_coordinator(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    before = len([c for c in api.mock_calls if c[1].path == '/api/charge/stats'])
    await _press(hass)
    await hass.async_block_till_done()
    after = len([c for c in api.mock_calls if c[1].path == '/api/charge/stats'])
    assert after == before + 1


async def test_double_press_ignored(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _press(hass)
    freezer.tick(timedelta(seconds=5))
    await _press(hass)
    assert len(_posts(api)) == 1
    assert 'Ignoring repeated press' in caplog.text
    freezer.tick(timedelta(seconds=6))
    await _press(hass)
    assert len(_posts(api)) == 2


@pytest.mark.parametrize(
    ('kwargs', 'text'),
    [({'status': 422}, 'rejected'), ({'status': 503}, 'Could not reach'), ({'status': 401}, 'token was rejected')],
)
async def test_press_failure_raises_translated_error(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker, kwargs: dict, text: str
) -> None:
    api.clear_requests()
    api.post(f'{BASE}/expense/', **kwargs)
    api.get(f'{BASE}/car/', json=[])
    with pytest.raises(HomeAssistantError, match=text):
        await _press(hass)


async def test_failed_press_does_not_block_retry(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    api.clear_requests()
    api.post(f'{BASE}/expense/', status=503)
    with pytest.raises(HomeAssistantError):
        await _press(hass)
    api.clear_requests()
    api.post(f'{BASE}/expense/', status=201, json={})
    api.get(f'{BASE}/car/', json=[{'id': CAR_A, 'name': 'Alpha', 'sale_date': None}])
    api.get(f'{BASE}/charge/stats', json={'total': {}, 'per_car': []})
    await _press(hass)
    assert len(_posts(api)) == 1


async def test_button_unavailable_for_retired_car(hass: HomeAssistant, api: AiohttpClientMocker) -> None:
    retired = MockConfigEntry(
        domain=DOMAIN,
        unique_id='tester',
        title='Chargelogger (tester)',
        data={CONF_URL: BASE, CONF_TOKEN: TOKEN},
        subentries_data=[preset(car_id=CAR_OLD)],
    )
    retired.add_to_hass(hass)
    await hass.config_entries.async_setup(retired.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(BUTTON).state == 'unavailable'


async def test_add_preset_via_subentry_flow(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    result = await hass.config_entries.subentries.async_init(
        (setup.entry_id, SUBENTRY_PRESET), context={'source': SOURCE_USER}
    )
    assert result['type'] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result['flow_id'],
        {
            'name': 'Car wash',
            'car_id': CAR_A,
            'category': 'cleaning',
            'kind': 'expense',
            'amount': 12.5,
            'note': '',
        },
    )
    assert result['type'] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    created = next(sub for sub in setup.subentries.values() if sub.title == 'Car wash')
    assert created.data == {'car_id': CAR_A, 'category': 'cleaning', 'kind': 'expense', 'amount': 1250}
    assert hass.states.get('button.car_wash') is not None


async def test_reconfigure_preset(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    subentry_id = next(iter(setup.subentries))
    result = await hass.config_entries.subentries.async_init(
        (setup.entry_id, SUBENTRY_PRESET), context={'source': SOURCE_RECONFIGURE, 'subentry_id': subentry_id}
    )
    assert result['type'] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result['flow_id'],
        {
            'name': 'Garage fee',
            'car_id': CAR_A,
            'category': 'tolls_parking',
            'kind': 'income',
            'amount': 3.99,
            'note': 'x',
        },
    )
    assert result['type'] is FlowResultType.ABORT
    await hass.async_block_till_done()
    data = setup.subentries[subentry_id].data
    assert data['amount'] == 399
    assert data['kind'] == 'income'


async def test_preset_flow_aborts_when_entry_not_loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PRESET), context={'source': SOURCE_USER}
    )
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'entry_not_loaded'
