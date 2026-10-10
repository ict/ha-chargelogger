"""Config flow, reauth, reconfigure and options tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.chargelogger.const import CONF_CURRENCY, CONF_TOKEN, CONF_URL, DOMAIN

from .conftest import BASE, TOKEN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

USER_INPUT = {CONF_URL: f'{BASE}/', CONF_TOKEN: TOKEN}


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={'source': config_entries.SOURCE_USER})


async def test_user_flow_success(hass: HomeAssistant, api: AiohttpClientMocker) -> None:
    result = await _start(hass)
    assert result['type'] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result['flow_id'], USER_INPUT)
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['title'] == 'Chargelogger (tester)'
    assert result['data'] == {CONF_URL: BASE, CONF_TOKEN: TOKEN}
    assert result['result'].unique_id == 'tester'
    assert result['options'] == {CONF_CURRENCY: 'EUR'}


async def test_invalid_auth_then_recover(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f'{BASE}/users/me', status=401)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], USER_INPUT)
    assert result['type'] is FlowResultType.FORM
    assert result['errors'] == {'base': 'invalid_auth'}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f'{BASE}/users/me', json={'username': 'tester'})
    result = await hass.config_entries.flow.async_configure(result['flow_id'], USER_INPUT)
    assert result['type'] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize('kwargs', [{'status': 502}, {'exc': TimeoutError()}])
async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs: dict) -> None:
    aioclient_mock.get(f'{BASE}/users/me', **kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], USER_INPUT)
    assert result['errors'] == {'base': 'cannot_connect'}


async def test_already_configured(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], USER_INPUT)
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'already_configured'


async def test_reauth_success(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    result = await setup.start_reauth_flow(hass)
    assert result['step_id'] == 'reauth_confirm'
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {CONF_TOKEN: 'clk_new'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'reauth_successful'
    assert setup.data[CONF_TOKEN] == 'clk_new'


async def test_reauth_invalid_and_wrong_account(
    hass: HomeAssistant, setup: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f'{BASE}/users/me', status=401)
    result = await setup.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {CONF_TOKEN: 'clk_bad'})
    assert result['errors'] == {'base': 'invalid_auth'}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f'{BASE}/users/me', json={'username': 'someone-else'})
    result = await hass.config_entries.flow.async_configure(result['flow_id'], {CONF_TOKEN: 'clk_other'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'unique_id_mismatch'


async def test_reauth_triggered_by_401_on_refresh(
    hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker
) -> None:
    api.clear_requests()
    api.get(f'{BASE}/car/', status=401)
    coordinator = setup.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert any(flow['context']['source'] == 'reauth' for flow in hass.config_entries.flow.async_progress())


async def test_reconfigure(hass: HomeAssistant, setup: MockConfigEntry, api: AiohttpClientMocker) -> None:
    result = await setup.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_URL: f'{BASE}/', CONF_TOKEN: 'clk_rotated'}
    )
    assert result['reason'] == 'reconfigure_successful'
    assert setup.data == {CONF_URL: BASE, CONF_TOKEN: 'clk_rotated'}


async def test_options_currency(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(setup.entry_id)
    bad = await hass.config_entries.options.async_configure(result['flow_id'], {CONF_CURRENCY: 'euro'})
    assert bad['errors'] == {CONF_CURRENCY: 'invalid_currency'}
    done = await hass.config_entries.options.async_configure(result['flow_id'], {CONF_CURRENCY: ' usd '})
    assert done['type'] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options == {CONF_CURRENCY: 'USD'}
    state = hass.states.get('sensor.chargelogger_tester_charging_cost_this_month')
    assert state.attributes['unit_of_measurement'] == 'USD'
