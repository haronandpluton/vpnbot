from __future__ import annotations

import httpx
import pytest

import app.services.adsgram_client as client_module
from app.services.adsgram_client import (
    AdsGramAPIError,
    AdsGramClient,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []
    queued_responses: list[FakeResponse] = []
    queued_errors: list[Exception] = []

    def __init__(
        self,
        *,
        timeout=None,
        follow_redirects=None,
    ) -> None:
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.get_calls: list[dict] = []
        self.enter_count = 0
        self.exit_count = 0

        self.__class__.instances.append(self)

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        self.exit_count += 1
        return False

    async def get(
        self,
        url: str,
        **kwargs,
    ):
        self.get_calls.append(
            {
                "url": url,
                **kwargs,
            }
        )

        if self.__class__.queued_errors:
            raise self.__class__.queued_errors.pop(0)

        if not self.__class__.queued_responses:
            raise AssertionError(
                "No fake AdsGram response queued"
            )

        return self.__class__.queued_responses.pop(0)


@pytest.fixture(autouse=True)
def reset_fake_http(monkeypatch):
    FakeAsyncClient.instances = []
    FakeAsyncClient.queued_responses = []
    FakeAsyncClient.queued_errors = []

    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        FakeAsyncClient,
    )


def make_client(
    *,
    api_url: str = (
        "https://api.adsgram.ai/confirm_conversion"
    ),
    api_token: str = "secret-token",
    timeout_seconds: float = 10.0,
) -> AdsGramClient:
    return AdsGramClient(
        api_url=api_url,
        api_token=api_token,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.asyncio
async def test_confirm_conversion_sends_expected_request():
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            status_code=200,
            text="OK",
        )
    ]

    client = make_client(
        api_url=(
            "https://api.adsgram.ai/"
            "confirm_conversion///"
        ),
        timeout_seconds=7.5,
    )

    result = await client.confirm_conversion(
        telegram_id=123456789,
        campaign_id="campaign_42",
        goal_type=2,
    )

    assert result.status_code == 200
    assert result.response_body == "OK"

    assert len(FakeAsyncClient.instances) == 1

    fake_http = FakeAsyncClient.instances[0]

    assert fake_http.timeout == 7.5
    assert fake_http.follow_redirects is False
    assert fake_http.enter_count == 1
    assert fake_http.exit_count == 1

    assert fake_http.get_calls == [
        {
            "url": (
                "https://api.adsgram.ai/"
                "confirm_conversion"
            ),
            "params": {
                "token": "secret-token",
                "tgid": "123456789",
                "campaignid": "campaign_42",
                "goaltype": "2",
            },
            "headers": {
                "Accept": "*/*",
                "User-Agent": "PresentVPN/1.0",
            },
        }
    ]


@pytest.mark.asyncio
async def test_confirm_conversion_truncates_response_body():
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            status_code=200,
            text="x" * 1500,
        )
    ]

    result = await make_client().confirm_conversion(
        telegram_id=123,
        campaign_id="campaign_42",
        goal_type=1,
    )

    assert result.response_body == "x" * 1000


@pytest.mark.asyncio
async def test_empty_token_is_rejected_without_http_request():
    client = make_client(api_token="   ")

    with pytest.raises(
        AdsGramAPIError,
        match="ADSGRAM_API_TOKEN is empty",
    ) as exc_info:
        await client.confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=1,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
async def test_invalid_api_url_is_rejected():
    client = make_client(
        api_url="api.adsgram.ai/confirm_conversion"
    )

    with pytest.raises(
        AdsGramAPIError,
        match="ADSGRAM_API_URL must use HTTPS",
    ) as exc_info:
        await client.confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=1,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []

@pytest.mark.asyncio
async def test_http_api_url_is_rejected():
    client = make_client(
        api_url=(
            "http://api.adsgram.ai/"
            "confirm_conversion"
        )
    )

    with pytest.raises(
        AdsGramAPIError,
        match="ADSGRAM_API_URL must use HTTPS",
    ) as exc_info:
        await client.confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=1,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
async def test_invalid_telegram_id_is_rejected():
    with pytest.raises(
        AdsGramAPIError,
        match="telegram_id must be positive",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=0,
            campaign_id="campaign_42",
            goal_type=1,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
async def test_empty_campaign_id_is_rejected():
    with pytest.raises(
        AdsGramAPIError,
        match="campaign_id is empty",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=123,
            campaign_id="   ",
            goal_type=1,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal_type",
    [
        0,
        4,
        -1,
    ],
)
async def test_invalid_goal_type_is_rejected(
    goal_type,
):
    with pytest.raises(
        AdsGramAPIError,
        match="goal_type must be one of",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=goal_type,
        )

    assert exc_info.value.retryable is False
    assert FakeAsyncClient.instances == []


@pytest.mark.asyncio
async def test_network_error_is_retryable_and_hides_token():
    request = httpx.Request(
        "GET",
        "https://api.adsgram.ai/confirm_conversion",
    )

    FakeAsyncClient.queued_errors = [
        httpx.ConnectError(
            "connection failed",
            request=request,
        )
    ]

    with pytest.raises(
        AdsGramAPIError,
        match="AdsGram request failed",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=1,
        )

    error = exc_info.value

    assert error.retryable is True
    assert error.status_code is None
    assert error.response_body is None
    assert "secret-token" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code",
    [
        408,
        425,
        429,
        500,
        502,
        503,
        599,
    ],
)
async def test_temporary_http_errors_are_retryable(
    status_code,
):
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            status_code=status_code,
            text="temporary failure",
        )
    ]

    with pytest.raises(
        AdsGramAPIError,
        match=f"HTTP {status_code}",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=3,
        )

    error = exc_info.value

    assert error.retryable is True
    assert error.status_code == status_code
    assert error.response_body == "temporary failure"
    assert "secret-token" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code",
    [
        300,
        400,
        401,
        403,
        404,
        409,
        422,
    ],
)
async def test_permanent_http_errors_are_not_retryable(
    status_code,
):
    FakeAsyncClient.queued_responses = [
        FakeResponse(
            status_code=status_code,
            text="permanent failure",
        )
    ]

    with pytest.raises(
        AdsGramAPIError,
        match=f"HTTP {status_code}",
    ) as exc_info:
        await make_client().confirm_conversion(
            telegram_id=123,
            campaign_id="campaign_42",
            goal_type=2,
        )

    error = exc_info.value

    assert error.retryable is False
    assert error.status_code == status_code
    assert error.response_body == "permanent failure"
    assert "secret-token" not in str(error)