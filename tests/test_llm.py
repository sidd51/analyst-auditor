from src.llm import affordable_max_tokens, in_flight_retry_seconds


def test_in_flight_budget_reads_retry_after() -> None:
    exc = RuntimeError(
        "Error code: 402 - {'error': {'metadata': {'reason': "
        "'in_flight_budget_exhausted', 'headers': {'Retry-After': '120'}}}}"
    )
    assert in_flight_retry_seconds(exc) == 120


def test_empty_wallet_402_is_not_an_in_flight_wait() -> None:
    exc = RuntimeError(
        "This request requires more credits, or fewer max_tokens. "
        "You requested up to 2000 tokens, but can only afford 1782."
    )
    assert in_flight_retry_seconds(exc) is None
    assert affordable_max_tokens(exc) == 1782


def test_other_errors_are_not_retried() -> None:
    assert in_flight_retry_seconds(RuntimeError("timeout")) is None
    assert affordable_max_tokens(RuntimeError("timeout")) is None
