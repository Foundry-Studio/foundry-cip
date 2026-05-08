# foundry: kind=test domain=client-intelligence-platform
"""Smoke tests for ``cip.integration_mesh.exceptions``."""
from __future__ import annotations

import pytest

from cip.integration_mesh.exceptions import (
    AuthenticationError,
    ConnectorError,
    KnowledgeMetadataValidationError,
    PersistenceError,
    RateLimitExceeded,
    SchemaDriftError,
    SyncAlreadyRunningError,
    SyncLockUnavailableError,
    TimezoneNaiveError,
)


class TestHierarchy:
    @pytest.mark.parametrize(
        "cls",
        [
            AuthenticationError,
            RateLimitExceeded,
            SchemaDriftError,
            PersistenceError,
            TimezoneNaiveError,
            # M3 §4.7 — both inherit from ConnectorError; distinct retry semantics.
            SyncAlreadyRunningError,
            SyncLockUnavailableError,
        ],
    )
    def test_inherit_connector_error(self, cls: type[Exception]) -> None:
        assert issubclass(cls, ConnectorError)

    def test_connector_error_inherits_exception(self) -> None:
        assert issubclass(ConnectorError, Exception)

    def test_metadata_validation_inherits_value_error(self) -> None:
        # v5.2 (Round-6 Call A): KnowledgeMetadataValidationError is a
        # CIP-internal contract violation, not a connector author's fault.
        # Inherits from ValueError, NOT ConnectorError.
        assert issubclass(KnowledgeMetadataValidationError, ValueError)
        assert not issubclass(KnowledgeMetadataValidationError, ConnectorError)

    def test_sync_already_running_distinct_from_lock_unavailable(self) -> None:
        # M3 §2.6: distinct retry semantics — SyncAlreadyRunningError is
        # NOT retryable (first sync is already producing the output);
        # SyncLockUnavailableError is transient infra and IS retryable.
        # They must be separate classes so callers can branch on type.
        assert not issubclass(SyncAlreadyRunningError, SyncLockUnavailableError)
        assert not issubclass(SyncLockUnavailableError, SyncAlreadyRunningError)


class TestRateLimitExceeded:
    def test_carries_retry_after_seconds(self) -> None:
        err = RateLimitExceeded(retry_after_seconds=42.5)
        assert err.retry_after_seconds == 42.5

    def test_accepts_message_arg(self) -> None:
        err = RateLimitExceeded(10.0, "rate limit hit")
        assert err.retry_after_seconds == 10.0
        assert "rate limit hit" in str(err)

    def test_raise_and_catch(self) -> None:
        with pytest.raises(RateLimitExceeded) as exc:
            raise RateLimitExceeded(retry_after_seconds=2.0)
        assert exc.value.retry_after_seconds == 2.0


class TestRaiseSubtypes:
    @pytest.mark.parametrize(
        "cls",
        [
            AuthenticationError,
            SchemaDriftError,
            PersistenceError,
            TimezoneNaiveError,
        ],
    )
    def test_raise_with_message(self, cls: type[ConnectorError]) -> None:
        with pytest.raises(ConnectorError) as exc:
            raise cls("boom")
        assert "boom" in str(exc.value)

    def test_metadata_validation_raise(self) -> None:
        with pytest.raises(KnowledgeMetadataValidationError) as exc:
            raise KnowledgeMetadataValidationError("missing keys")
        assert "missing keys" in str(exc.value)
