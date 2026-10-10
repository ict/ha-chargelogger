"""Data update coordinator for Chargelogger."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Car,
    ChargeloggerAuthError,
    ChargeloggerClient,
    ChargeloggerConnectionError,
    ChargeloggerError,
    ExpenseStats,
    Stats,
)
from .const import DOMAIN, SCAN_INTERVAL, WASH_CATEGORY

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type ChargeloggerConfigEntry = ConfigEntry[ChargeloggerCoordinator]


@dataclass(frozen=True, slots=True)
class ChargeloggerData:
    """Snapshot of one coordinator update."""

    month_start: datetime
    cars: dict[str, Car]
    total: Stats
    per_car: dict[str, Stats]
    expenses_total: ExpenseStats = field(default_factory=ExpenseStats)
    expenses_per_car: dict[str, ExpenseStats] = field(default_factory=dict)
    last_wash: datetime | None = None
    last_wash_per_car: dict[str, datetime | None] = field(default_factory=dict)

    @property
    def active_cars(self) -> dict[str, Car]:
        """Cars that are not retired."""
        return {car_id: car for car_id, car in self.cars.items() if not car.retired}

    def scope(self, car_id: str | None) -> ScopeData | None:
        """Everything a sensor shows for the account (None) or one active car; None if the car is gone."""
        if car_id is None:
            return ScopeData(self.total, self.expenses_total, self.last_wash)
        if car_id not in self.active_cars:
            return None
        return ScopeData(
            self.per_car.get(car_id, Stats()),
            self.expenses_per_car.get(car_id, ExpenseStats()),
            self.last_wash_per_car.get(car_id),
        )


@dataclass(frozen=True, slots=True)
class ScopeData:
    """This month's charge and expense statistics plus the last car wash, for one scope."""

    charges: Stats
    expenses: ExpenseStats
    last_wash: datetime | None


def month_start(now: datetime) -> datetime:
    """Return the start of the month of ``now`` in its own time zone."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class ChargeloggerCoordinator(DataUpdateCoordinator[ChargeloggerData]):
    """Fetch cars and this month's statistics."""

    config_entry: ChargeloggerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ChargeloggerConfigEntry, client: ChargeloggerClient) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.client = client
        self.account_device_id = ''

    async def _async_update_data(self) -> ChargeloggerData:
        start = month_start(dt_util.now())
        try:
            cars = await self.client.get_cars()
            stats = await self.client.get_stats(start)
            expenses = await self.client.get_expenses(from_date=start)
            last_wash = await self.client.get_last_expense_date(category=WASH_CATEGORY)
            last_wash_per_car = {
                car.id: await self.client.get_last_expense_date(category=WASH_CATEGORY, car_id=car.id)
                for car in cars
                if not car.retired
            }
        except ChargeloggerAuthError as err:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key='invalid_auth') from err
        except ChargeloggerError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key='update_failed', translation_placeholders={'error': str(err)}
            ) from err
        return ChargeloggerData(
            month_start=start,
            cars={car.id: car for car in cars},
            total=stats.total,
            per_car=stats.per_car,
            expenses_total=ExpenseStats.from_api(expenses),
            expenses_per_car={
                car_id: ExpenseStats.from_api([e for e in expenses if e.get('car_id') == car_id])
                for car_id in {str(e.get('car_id')) for e in expenses}
            },
            last_wash=last_wash,
            last_wash_per_car=last_wash_per_car,
        )

    async def _async_write(self, request: Awaitable[Any], rejected_key: str) -> Any:
        """Run a write request, map errors to translated HomeAssistantErrors, then refresh."""
        try:
            result = await request
        except ChargeloggerAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key='invalid_auth') from err
        except ChargeloggerConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='cannot_connect',
                translation_placeholders={'error': str(err)},
            ) from err
        except ChargeloggerError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=rejected_key,
                translation_placeholders={'error': str(err)},
            ) from err
        await self.async_request_refresh()
        return result

    async def async_create_charge(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a charge and refresh; returns the stored charge."""
        return await self._async_write(self.client.create_charge(body), 'charge_rejected')

    async def async_get_cpos(self) -> list[dict[str, Any]]:
        """Return the user's CPOs; raises a translated HomeAssistantError on failure."""
        try:
            return await self.client.get_cpos()
        except ChargeloggerAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key='invalid_auth') from err
        except ChargeloggerError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key='cannot_connect',
                translation_placeholders={'error': str(err)},
            ) from err

    async def async_create_expense(
        self,
        *,
        car_id: str,
        category: str,
        kind: str,
        amount_cents: int,
        note: str | None = None,
        date: datetime | None = None,
    ) -> None:
        """Create an expense and refresh; raises a translated HomeAssistantError on failure."""
        body: dict[str, Any] = {
            'date': (date or dt_util.now()).isoformat(),
            'car_id': car_id,
            'category': category,
            'kind': kind,
            'amount': amount_cents,
        }
        if note:
            body['note'] = note
        await self._async_write(self.client.create_expense(body), 'expense_rejected')
