"""Dated, sourced Australian rule parameters; every value carries its status and source."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from importlib.resources import files
from types import MappingProxyType
import tomllib

from financial_simulations.dates import as_date


# projected: statutory indexation applied with an assumed index path (later years only).
STATUSES = ("enacted", "published_indexed", "assumption", "projected")


class UnsupportedRule(ValueError):
    """A rule applies to the scenario but is deliberately not implemented yet."""


@dataclass(frozen=True)
class Parameter:
    name: str
    value: object
    status: str
    source: str
    note: str = ""
    units: str = ""


@dataclass(frozen=True)
class RuleSet:
    financial_year: str
    start: date
    end: date
    verified: date
    parameters: MappingProxyType
    sources: MappingProxyType
    sha256: str

    def __getitem__(self, name):
        try:
            return self.parameters[name].value
        except KeyError as exc:
            raise KeyError(f"{self.financial_year} rule set has no parameter {name!r}.") from exc

    def covers(self, day) -> bool:
        return self.start <= as_date(day) <= self.end

    def assumptions(self) -> list[Parameter]:
        return [p for p in self.parameters.values() if p.status in ("assumption", "projected")]

    def manifest(self) -> dict:
        return {"financial_year": self.financial_year, "verified": str(self.verified), "sha256": self.sha256,
                "assumptions": {p.name: p.note for p in self.assumptions()}}

    def derive(self, financial_year: str, changes: dict, sources: dict | None = None) -> "RuleSet":
        """A later year's rule set: unchanged parameters keep their value and status, ``changes`` replace them."""
        first = int(financial_year[:4])
        parameters = dict(self.parameters)
        all_sources = {**self.sources, **(sources or {})}
        for name, parameter in changes.items():
            if parameter.status not in STATUSES or parameter.source not in all_sources:
                raise ValueError(f"{name}: invalid status or source.")
            parameters[name] = parameter
        digest = sha256((self.sha256 + financial_year + repr(sorted((k, repr(v)) for k, v in changes.items()))).encode())
        return RuleSet(financial_year, date(first, 7, 1), date(first + 1, 6, 30), self.verified,
                       MappingProxyType(parameters), MappingProxyType(all_sources), digest.hexdigest())


def load_ruleset(financial_year: str = "2026-27") -> RuleSet:
    """Load a packaged rule set; unknown statuses or sources fail rather than default."""
    raw = files("financial_simulations.rules.au").joinpath(f"fy{financial_year.replace('-', '_')}.toml").read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    meta = config["ruleset"]
    sources = {s["id"]: s for s in config["sources"]}
    if len(sources) != len(config["sources"]):
        raise ValueError("Rule source identifiers must be unique.")
    parameters = {}
    for name, entry in config["parameters"].items():
        if entry.get("status") not in STATUSES:
            raise ValueError(f"{name}: status must be one of {STATUSES}.")
        if entry.get("source") not in sources:
            raise ValueError(f"{name}: unknown source {entry.get('source')!r}.")
        parameters[name] = Parameter(name, entry["value"], entry["status"], entry["source"],
                                     entry.get("note", ""), entry.get("units", ""))
    ruleset = RuleSet(meta["financial_year"], as_date(meta["start"]), as_date(meta["end"]), as_date(meta["verified"]),
                      MappingProxyType(parameters), MappingProxyType(sources), sha256(raw).hexdigest())
    if ruleset.financial_year != financial_year or (ruleset.start.month, ruleset.start.day) != (7, 1):
        raise ValueError("Rule set metadata must match its financial year starting 1 July.")
    return ruleset


def financial_year_of(day) -> str:
    """Australian income year label, e.g. 2026-07-01 -> '2026-27'."""
    day = as_date(day)
    first = day.year if day.month >= 7 else day.year - 1
    return f"{first}-{(first + 1) % 100:02d}"
