"""Config flow, options flow and preset subentry flow for Chargelogger."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ChargeloggerAuthError, ChargeloggerClient, ChargeloggerError
from .const import (
    CATEGORIES,
    CONF_AMOUNT,
    CONF_CAR_ID,
    CONF_CATEGORY,
    CONF_CURRENCY,
    CONF_KIND,
    CONF_NOTE,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_CURRENCY,
    DOMAIN,
    KINDS,
    SUBENTRY_PRESET,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

CURRENCY_RE = re.compile(r'^[A-Z]{3}$')

URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL, autocomplete='url'))
TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete='off'))


class ChargeloggerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ChargeloggerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """Presets are subentries."""
        return {SUBENTRY_PRESET: PresetSubentryFlow}

    async def _async_validate(self, url: str, token: str) -> tuple[str | None, str | None]:
        """Return (username, error_key)."""
        client = ChargeloggerClient(async_get_clientsession(self.hass), url, token)
        try:
            return await client.get_username(), None
        except ChargeloggerAuthError:
            return None, 'invalid_auth'
        except ChargeloggerError:
            return None, 'cannot_connect'

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username, error = await self._async_validate(user_input[CONF_URL], user_input[CONF_TOKEN])
            if username is not None:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f'Chargelogger ({username})',
                    data={CONF_URL: user_input[CONF_URL].rstrip('/'), CONF_TOKEN: user_input[CONF_TOKEN]},
                    options={CONF_CURRENCY: DEFAULT_CURRENCY},
                )
            errors['base'] = error or 'unknown'
        schema = probatio.Schema(
            {
                probatio.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, 'https://')): URL_SELECTOR,
                probatio.Required(CONF_TOKEN): TOKEN_SELECTOR,
            }
        )
        return self.async_show_form(step_id='user', data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after a 401."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            username, error = await self._async_validate(entry.data[CONF_URL], user_input[CONF_TOKEN])
            if username is not None:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]})
            errors['base'] = error or 'unknown'
        return self.async_show_form(
            step_id='reauth_confirm',
            data_schema=probatio.Schema({probatio.Required(CONF_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change URL or token."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            username, error = await self._async_validate(user_input[CONF_URL], user_input[CONF_TOKEN])
            if username is not None:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_URL: user_input[CONF_URL].rstrip('/'), CONF_TOKEN: user_input[CONF_TOKEN]},
                )
            errors['base'] = error or 'unknown'
        schema = probatio.Schema(
            {
                probatio.Required(CONF_URL, default=entry.data[CONF_URL]): URL_SELECTOR,
                probatio.Required(CONF_TOKEN): TOKEN_SELECTOR,
            }
        )
        return self.async_show_form(step_id='reconfigure', data_schema=schema, errors=errors)


class ChargeloggerOptionsFlow(OptionsFlow):
    """Options: display currency."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit the currency."""
        errors: dict[str, str] = {}
        if user_input is not None:
            currency = user_input[CONF_CURRENCY].strip().upper()
            if CURRENCY_RE.match(currency):
                return self.async_create_entry(data={CONF_CURRENCY: currency})
            errors[CONF_CURRENCY] = 'invalid_currency'
        current = self.config_entry.options.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        return self.async_show_form(
            step_id='init',
            data_schema=probatio.Schema(
                {probatio.Required(CONF_CURRENCY, default=current): TextSelector()},
            ),
            errors=errors,
        )


class PresetSubentryFlow(ConfigSubentryFlow):
    """Add or edit a quick-action preset."""

    def _schema(self, defaults: Mapping[str, Any]) -> probatio.Schema:
        entry = self._get_entry()
        cars = entry.runtime_data.data.active_cars
        car_options = [SelectOptionDict(value=car.id, label=car.name) for car in cars.values()]
        fields: dict[Any, Any] = {
            probatio.Required('name', default=defaults.get('name', '')): TextSelector(),
            probatio.Required(CONF_CAR_ID, default=defaults.get(CONF_CAR_ID, probatio.UNDEFINED)): SelectSelector(
                SelectSelectorConfig(options=car_options, mode=SelectSelectorMode.DROPDOWN)
            ),
            probatio.Required(CONF_CATEGORY, default=defaults.get(CONF_CATEGORY, probatio.UNDEFINED)): SelectSelector(
                SelectSelectorConfig(
                    options=CATEGORIES, translation_key=CONF_CATEGORY, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            probatio.Required(CONF_KIND, default=defaults.get(CONF_KIND, 'expense')): SelectSelector(
                SelectSelectorConfig(options=KINDS, translation_key=CONF_KIND, mode=SelectSelectorMode.DROPDOWN)
            ),
            probatio.Required(CONF_AMOUNT, default=defaults.get(CONF_AMOUNT, probatio.UNDEFINED)): NumberSelector(
                NumberSelectorConfig(min=0.01, max=1_000_000, step=0.01, mode=NumberSelectorMode.BOX)
            ),
            probatio.Optional(CONF_NOTE, default=defaults.get(CONF_NOTE, '')): TextSelector(),
        }
        return probatio.Schema(fields)

    @staticmethod
    def _to_stored(user_input: dict[str, Any]) -> dict[str, Any]:
        data = {key: user_input[key] for key in (CONF_CAR_ID, CONF_CATEGORY, CONF_KIND)}
        data[CONF_AMOUNT] = round(float(user_input[CONF_AMOUNT]) * 100)
        if note := user_input.get(CONF_NOTE, '').strip():
            data[CONF_NOTE] = note
        return data

    def _require_loaded(self) -> bool:
        return self._get_entry().state is ConfigEntryState.LOADED

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Create a preset."""
        if not self._require_loaded():
            return self.async_abort(reason='entry_not_loaded')
        if user_input is not None:
            return self.async_create_entry(title=user_input['name'].strip(), data=self._to_stored(user_input))
        return self.async_show_form(step_id='user', data_schema=self._schema({}))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Edit a preset."""
        if not self._require_loaded():
            return self.async_abort(reason='entry_not_loaded')
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input['name'].strip(),
                data=self._to_stored(user_input),
            )
        defaults = dict(subentry.data) | {'name': subentry.title, CONF_AMOUNT: subentry.data[CONF_AMOUNT] / 100}
        return self.async_show_form(step_id='reconfigure', data_schema=self._schema(defaults))
