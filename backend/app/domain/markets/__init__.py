"""Market domain module exports."""

from .catalog import (
    MARKET_CATALOG,
    MarketCapabilities,
    MarketCatalog,
    MarketCatalogEntry,
    MarketCatalogError,
    get_market_catalog,
)
from .market import Market, SUPPORTED_MARKET_CODES, UnsupportedMarketError
from .mic import MicFacts
from .mic_aliases import (
    MicAliasDefinition,
    MicAliasRegistry,
    MicAliasResolution,
    mic_alias_registry,
)
from .registry import BenchmarkFacts, MarketProfile, MarketRegistry, market_registry
from .symbol_suffixes import (
    MarketSymbolSuffixDefinition,
    MarketSymbolSuffixRegistry,
    market_symbol_suffix_registry,
)

__all__ = [
    "MARKET_CATALOG",
    "Market",
    "MarketCapabilities",
    "MarketCatalog",
    "MarketCatalogEntry",
    "MarketCatalogError",
    "MarketProfile",
    "MarketRegistry",
    "BenchmarkFacts",
    "MicFacts",
    "MicAliasDefinition",
    "MicAliasRegistry",
    "MicAliasResolution",
    "MarketSymbolSuffixDefinition",
    "MarketSymbolSuffixRegistry",
    "SUPPORTED_MARKET_CODES",
    "UnsupportedMarketError",
    "get_market_catalog",
    "market_registry",
    "mic_alias_registry",
    "market_symbol_suffix_registry",
]
