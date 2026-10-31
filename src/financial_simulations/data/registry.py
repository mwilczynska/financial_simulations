"""Explicit aliases and return semantics, reviewed against upstream methods."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Asset:
    identifier: str
    filename: str
    methodology: str
    aliases: tuple[str, ...] = ()
    currency: str = "USD"
    level_column: str = "Adj Close"
    return_column: str = "Total Return"
    return_semantics: str = "Reinvested total-return level or documented proxy; supplied costs retained."

    def metadata(self) -> dict:
        return asdict(self)


_ASSETS = (
    Asset("USLCAP", "us_large_cap_sp500.csv", "methodology_uslcap.md"),
    Asset("USLCAP2X", "us_large_cap_2x_sp500.csv", "methodology_uslcap2x.md", ("USLCAP2x",)),
    Asset("USLCAP3X", "us_large_cap_3x_sp500.csv", "methodology_uslcap3x.md", ("USLCAP3x",)),
    Asset("STT", "short_term_us_treasury.csv", "methodology_stt.md"),
    Asset("STT2X", "short_term_us_treasury_2x.csv", "methodology_stt2x.md", ("STT2x",)),
    Asset("ITT", "intermediate_term_us_treasury.csv", "methodology_itt.md"),
    Asset("ITT2X", "intermediate_term_us_treasury_2x.csv", "methodology_itt2x.md", ("ITT2x",)),
    Asset("ITT3X", "intermediate_term_us_treasury_3x.csv", "methodology_itt3x.md", ("ITT3x",)),
    Asset("LTT", "long_term_us_treasury.csv", "methodology_ltt.md"),
    Asset("LTT2X", "long_term_us_treasury_2x.csv", "methodology_ltt2x.md", ("LTT2x",)),
    Asset("LTT3X", "long_term_us_treasury_3x.csv", "methodology_ltt3x.md", ("LTT3x",)),
    Asset("GOLDPM", "gold.csv", "methodology_goldpm.md"),
    Asset("GOLD2X", "gold_2x.csv", "methodology_gold2x.md", ("GOLDPM2x", "GOLDPM2X")),
    Asset("CMDTY", "broad_commodities.csv", "methodology_cmdty.md", ("COMM",)),
    Asset("GLSTOCK", "global_stocks.csv", "methodology_glstock.md"),
    Asset("GLSTOCK2X", "global_stocks_2x.csv", "methodology_glstock2x.md", ("GLSTOCK2x",)),
    Asset("GLBOND", "global_bonds.csv", "methodology_glbond.md"),
    Asset("GLBOND2X", "global_bonds_2x.csv", "methodology_glbond2x.md", ("GLBOND2x",)),
    Asset("GLSTBOND", "global_short_term_bonds.csv", "methodology_glstbond.md"),
)
ASSETS = {asset.identifier: asset for asset in _ASSETS}
_ALIASES = {alias: asset.identifier for asset in _ASSETS for alias in (asset.identifier, *asset.aliases)}


def resolve_asset(identifier: str) -> Asset:
    try:
        return ASSETS[_ALIASES[identifier]]
    except KeyError as exc:
        raise ValueError(f"Unknown investable asset {identifier!r}; CPI is an economic factor, not a holding.") from exc
