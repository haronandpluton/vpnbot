from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx


class CryptoBotAPIError(RuntimeError):
    pass


class CryptoBotClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_token: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    async def _get(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_token.strip():
            raise CryptoBotAPIError("CRYPTOBOT_API_TOKEN is empty")

        headers = {
            "Crypto-Pay-API-Token": self.api_token,
            "Accept": "application/json",
            "User-Agent": "PresentVPN/1.0",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{self.api_url}/{method}",
                params=params or {},
                headers=headers,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise CryptoBotAPIError(
                f"CryptoBot returned non-JSON response: HTTP {response.status_code}"
            ) from exc

        if response.status_code >= 400 or data.get("ok") is not True:
            raise CryptoBotAPIError(
                f"CryptoBot API error: HTTP {response.status_code}; payload={data!r}"
            )

        return data.get("result")

    async def create_invoice(
        self,
        *,
        asset: str,
        amount: Decimal,
        description: str,
        payload: str,
        expires_in: int,
    ) -> dict[str, Any]:
        result = await self._get(
            "createInvoice",
            {
                "asset": asset,
                "amount": str(amount),
                "description": description,
                "payload": payload,
                "expires_in": str(expires_in),
                "allow_comments": "false",
                "allow_anonymous": "false",
            },
        )
        if not isinstance(result, dict):
            raise CryptoBotAPIError(f"Unexpected createInvoice result: {result!r}")
        return result

    async def get_invoice(self, invoice_id: int | str) -> dict[str, Any] | None:
        result = await self._get("getInvoices", {"invoice_ids": str(invoice_id)})

        if isinstance(result, dict):
            items = result.get("items")
            if isinstance(items, list):
                for item in items:
                    if str(item.get("invoice_id")) == str(invoice_id):
                        return item
                return items[0] if items else None

            if str(result.get("invoice_id")) == str(invoice_id):
                return result

        if isinstance(result, list):
            for item in result:
                if str(item.get("invoice_id")) == str(invoice_id):
                    return item
            return result[0] if result else None

        raise CryptoBotAPIError(f"Unexpected getInvoices result: {result!r}")
