from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class AdsGramDeliveryResponse:
    status_code: int
    response_body: str


class AdsGramAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)

        self.retryable = retryable
        self.status_code = status_code
        self.response_body = response_body


class AdsGramClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.api_url = api_url.strip().rstrip("/")
        self.api_token = api_token.strip()
        self.timeout_seconds = timeout_seconds

    async def confirm_conversion(
        self,
        *,
        telegram_id: int,
        campaign_id: str,
        goal_type: int,
    ) -> AdsGramDeliveryResponse:
        self._validate_request(
            telegram_id=telegram_id,
            campaign_id=campaign_id,
            goal_type=goal_type,
        )

        params = {
            "token": self.api_token,
            "tgid": str(telegram_id),
            "campaignid": campaign_id,
            "goaltype": str(goal_type),
        }
        headers = {
            "Accept": "*/*",
            "User-Agent": "PresentVPN/1.0",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    self.api_url,
                    params=params,
                    headers=headers,
                )

        except httpx.RequestError as exc:
            # Не включаем URL запроса в текст ошибки:
            # в query-параметрах находится секретный token.
            raise AdsGramAPIError(
                (
                    "AdsGram request failed: "
                    f"{type(exc).__name__}"
                ),
                retryable=True,
            ) from exc

        response_body = response.text[:1000]

        if response.status_code != 200:
            retryable = self._is_retryable_http_status(
                response.status_code
            )

            raise AdsGramAPIError(
                (
                    "AdsGram API returned unexpected status: "
                    f"HTTP {response.status_code}"
                ),
                retryable=retryable,
                status_code=response.status_code,
                response_body=response_body,
            )

        return AdsGramDeliveryResponse(
            status_code=response.status_code,
            response_body=response_body,
        )

    def _validate_request(
        self,
        *,
        telegram_id: int,
        campaign_id: str,
        goal_type: int,
    ) -> None:
        if not self.api_token:
            raise AdsGramAPIError(
                "ADSGRAM_API_TOKEN is empty",
                retryable=False,
            )

        if not self.api_url.startswith("https://"):
            raise AdsGramAPIError(
                "ADSGRAM_API_URL must use HTTPS",
                retryable=False,
            )

        if telegram_id <= 0:
            raise AdsGramAPIError(
                "AdsGram telegram_id must be positive",
                retryable=False,
            )

        if not campaign_id.strip():
            raise AdsGramAPIError(
                "AdsGram campaign_id is empty",
                retryable=False,
            )

        if goal_type not in {1, 2, 3}:
            raise AdsGramAPIError(
                (
                    "AdsGram goal_type must be "
                    "one of: 1, 2, 3"
                ),
                retryable=False,
            )

    @staticmethod
    def _is_retryable_http_status(
        status_code: int,
    ) -> bool:
        return (
            status_code in {408, 425, 429}
            or 500 <= status_code <= 599
        )