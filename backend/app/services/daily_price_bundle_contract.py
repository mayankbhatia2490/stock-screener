"""Daily price bundle schema and metadata validation contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..domain.markets import market_registry

DAILY_PRICE_BUNDLE_SCHEMA_VERSION = "daily-price-bundle-v1"
DAILY_PRICE_MANIFEST_SCHEMA_VERSION = "daily-price-manifest-v1"
DAILY_PRICE_RELEASE_TAG = "daily-price-data"
DAILY_PRICE_BAR_PERIOD = "2y"
DAILY_PRICE_SUPPORTED_MARKETS: tuple[str, ...] = market_registry.supported_market_codes()
REQUIRED_DAILY_PRICE_MANIFEST_KEYS = (
    "market",
    "as_of_date",
    "source_revision",
    "bundle_asset_name",
    "sha256",
    "bar_period",
    "symbol_count",
)


def normalize_daily_price_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in DAILY_PRICE_SUPPORTED_MARKETS:
        raise ValueError(
            f"Unsupported daily price bundle market {market!r}. "
            f"Expected one of {sorted(DAILY_PRICE_SUPPORTED_MARKETS)}."
        )
    return normalized


def latest_daily_price_manifest_name(market: str) -> str:
    return f"daily-price-latest-{normalize_daily_price_market(market).lower()}.json"


def daily_price_sync_state_key(market: str) -> str:
    return f"github_sync.daily_prices.{normalize_daily_price_market(market).lower()}"


@dataclass(frozen=True)
class DailyPriceBundleMetadata:
    """Typed metadata contract shared by bundle manifests and streamed payloads."""

    schema_version: str
    market: str
    as_of_date: date
    source_revision: str
    bar_period: str
    symbol_count: int

    @classmethod
    def from_bundle_payload(
        cls,
        payload: dict[str, Any],
        *,
        expected_schema_version: str = DAILY_PRICE_BUNDLE_SCHEMA_VERSION,
        expected_bar_period: str = DAILY_PRICE_BAR_PERIOD,
        normalize_market: Callable[[str], str] = normalize_daily_price_market,
    ) -> "DailyPriceBundleMetadata":
        schema_version = str(payload.get("schema_version") or "")
        if schema_version != expected_schema_version:
            raise ValueError(
                "Unsupported daily price bundle schema version: "
                f"{payload.get('schema_version')!r}"
            )

        market = normalize_market(str(payload.get("market") or ""))
        as_of_date = cls._required_date(payload, "as_of_date", source="bundle")
        bar_period = cls._required_text(payload, "bar_period", source="bundle")
        if bar_period != expected_bar_period:
            raise ValueError(
                f"Unsupported daily price bundle bar_period {bar_period!r}; "
                f"expected {expected_bar_period!r}"
            )
        return cls(
            schema_version=schema_version,
            market=market,
            as_of_date=as_of_date,
            source_revision=cls._required_text(
                payload,
                "source_revision",
                source="bundle",
            ),
            bar_period=bar_period,
            symbol_count=cls._required_int(payload, "symbol_count", source="bundle"),
        )

    @classmethod
    def expected_from_manifest(
        cls,
        manifest: dict[str, Any],
        *,
        bundle_schema_version: str = DAILY_PRICE_BUNDLE_SCHEMA_VERSION,
        expected_bar_period: str = DAILY_PRICE_BAR_PERIOD,
        normalize_market: Callable[[str], str] = normalize_daily_price_market,
    ) -> "DailyPriceBundleMetadata":
        bar_period = cls._required_text(manifest, "bar_period", source="manifest")
        if bar_period != expected_bar_period:
            raise ValueError(
                f"Daily price manifest bar_period must be {expected_bar_period!r}"
            )
        return cls(
            schema_version=bundle_schema_version,
            market=normalize_market(
                cls._required_text(manifest, "market", source="manifest")
            ),
            as_of_date=cls._required_date(manifest, "as_of_date", source="manifest"),
            source_revision=cls._required_text(
                manifest,
                "source_revision",
                source="manifest",
            ),
            bar_period=bar_period,
            symbol_count=cls._required_int(manifest, "symbol_count", source="manifest"),
        )

    def assert_matches_manifest(self, expected: "DailyPriceBundleMetadata | None") -> None:
        if expected is None:
            return
        comparisons = (
            ("schema_version", self.schema_version, expected.schema_version),
            ("market", self.market, expected.market),
            ("as_of_date", self.as_of_date.isoformat(), expected.as_of_date.isoformat()),
            ("source_revision", self.source_revision, expected.source_revision),
            ("bar_period", self.bar_period, expected.bar_period),
            ("symbol_count", self.symbol_count, expected.symbol_count),
        )
        for key, actual, manifest_value in comparisons:
            if actual != manifest_value:
                raise ValueError(
                    f"Daily price bundle {key} {actual!r} "
                    f"does not match manifest {manifest_value!r}"
                )

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str, *, source: str) -> str:
        value = payload.get(key)
        if value in (None, ""):
            raise ValueError(f"Daily price {source} is missing {key}")
        return str(value)

    @classmethod
    def _required_date(cls, payload: dict[str, Any], key: str, *, source: str) -> date:
        return date.fromisoformat(cls._required_text(payload, key, source=source))

    @classmethod
    def _required_int(cls, payload: dict[str, Any], key: str, *, source: str) -> int:
        raw_value = cls._required_text(payload, key, source=source)
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError(
                f"Daily price {source} {key} must be an integer"
            ) from exc


def bundle_metadata_from_payload(payload: dict[str, Any]) -> DailyPriceBundleMetadata:
    return DailyPriceBundleMetadata.from_bundle_payload(payload)


def expected_bundle_metadata_from_manifest(
    manifest: dict[str, Any],
) -> DailyPriceBundleMetadata:
    return DailyPriceBundleMetadata.expected_from_manifest(manifest)
