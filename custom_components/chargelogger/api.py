"""Minimal async client for the Chargelogger REST API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from .const import REQUEST_TIMEOUT

if TYPE_CHECKING:
    from datetime import datetime


class ChargeloggerError(Exception):
    """Base error for the Chargelogger client."""


class ChargeloggerConnectionError(ChargeloggerError):
    """The server could not be reached or returned an unexpected response."""


class ChargeloggerAuthError(ChargeloggerError):
    """The token was rejected."""


class ChargeloggerRequestError(ChargeloggerError):
    """The server rejected the request (4xx other than 401)."""


@dataclass(frozen=True, slots=True)
class Car:
    """A car owned by the user."""

    id: str
    name: str
    retired: bool


@dataclass(frozen=True, slots=True)
class Stats:
    """Charge statistics bucket with converted units."""

    count: int = 0
    energy_kwh: float = 0.0
    cost: float = 0.0
    charges_without_price: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Stats:
        """Build from an API bucket (1/100 kWh and cents)."""
        return cls(
            count=int(data.get('count', 0)),
            energy_kwh=int(data.get('kwh_charged', 0)) / 100,
            cost=int(data.get('price_total', 0)) / 100,
            charges_without_price=int(data.get('charges_without_price', 0)),
        )


@dataclass(frozen=True, slots=True)
class StatsResult:
    """Total and per car statistics."""

    total: Stats
    per_car: dict[str, Stats]


async def _error_detail(resp: aiohttp.ClientResponse) -> str:
    """Return the API's error message (FastAPI `detail`), falling back to the status code."""
    try:
        detail = (await resp.json(content_type=None)).get('detail')
    except aiohttp.ClientError, ValueError, AttributeError:
        detail = None
    if isinstance(detail, list):  # pydantic validation errors
        detail = '; '.join(str(item.get('msg', item)) if isinstance(item, dict) else str(item) for item in detail)
    return f'HTTP {resp.status}: {detail}' if detail else f'HTTP {resp.status}'


class ChargeloggerClient:
    """Thin wrapper around aiohttp for the Chargelogger API."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        """Initialize the client."""
        self._session = session
        self._url = url.rstrip('/')
        self._headers = {'Authorization': f'Bearer {token}'}

    async def _request(self, method: str, path: str, *, params: dict[str, str] | None = None, json: Any = None) -> Any:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.request(
                    method, f'{self._url}{path}', headers=self._headers, params=params, json=json
                )
                async with resp:
                    if resp.status == 401:
                        raise ChargeloggerAuthError
                    if 400 <= resp.status < 500:
                        raise ChargeloggerRequestError(await _error_detail(resp))
                    if resp.status >= 500:
                        msg = f'HTTP {resp.status}'
                        raise ChargeloggerConnectionError(msg)
                    return await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise ChargeloggerConnectionError(str(err)) from err

    async def get_username(self) -> str:
        """Return the username of the token owner (validates credentials)."""
        data = await self._request('GET', '/users/me')
        if not isinstance(data, dict) or not data.get('username'):
            msg = 'Unexpected /users/me response'
            raise ChargeloggerConnectionError(msg)
        return str(data['username'])

    async def get_cars(self) -> list[Car]:
        """Return all cars of the user."""
        data = await self._request('GET', '/car/')
        return [Car(id=str(car['id']), name=str(car['name']), retired=car.get('sale_date') is not None) for car in data]

    async def get_stats(self, from_date: datetime) -> StatsResult:
        """Return statistics since ``from_date`` (timezone-aware)."""
        data = await self._request('GET', '/charge/stats', params={'from_date': from_date.isoformat()})
        return StatsResult(
            total=Stats.from_api(data['total']),
            per_car={str(bucket['car_id']): Stats.from_api(bucket) for bucket in data.get('per_car', [])},
        )

    async def get_cpos(self) -> list[dict[str, Any]]:
        """Return the user's charge point operators."""
        return await self._request('GET', '/cpo/')

    async def create_charge(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create a charge and return it as stored (incl. computed price)."""
        return await self._request('POST', '/charge/', json=body)

    async def create_expense(self, body: dict[str, Any]) -> None:
        """Create an expense or income record."""
        await self._request('POST', '/expense/', json=body)
