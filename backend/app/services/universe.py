"""Universe selection — the list of stocks a scan will look at."""

from __future__ import annotations

from app.core.errors import ApiError, NotConfigured
from app.engine import core


def choices() -> list[dict]:
    """Every universe the scanner accepts, with the cost of choosing it.

    Size is what the user actually needs to know here: the full NSE list is
    ~4x Nifty 500 and takes proportionally longer to scan, and it is the only
    option that needs Dhan credentials (it is built from the scrip master, not
    from a public index CSV).
    """
    out = []
    for name in core.UNIVERSE_CHOICES:
        needs_dhan = name == core.FULL_NSE_UNIVERSE
        out.append({
            "name": name,
            "source": "Dhan instrument master" if needs_dhan else "niftyindices.com",
            "requires_dhan": needs_dhan,
            "available": (not needs_dhan) or core.dhan_configured(),
            "approx_size": 2000 if needs_dhan else None,
        })
    return out


def resolve(names: list[str]) -> list[str]:
    """Ticker list for the selected universes, with a usable error on failure."""
    if not names:
        raise ApiError("Select at least one universe to scan.")
    unknown = [n for n in names if n not in core.UNIVERSE_CHOICES]
    if unknown:
        raise ApiError(f"Unknown universe: {', '.join(unknown)}")
    try:
        tickers = core.resolve_universes(names)
    except RuntimeError as exc:
        # resolve_universe() raises this when the full-NSE option is picked
        # without Dhan credentials; the message already names the fix.
        raise NotConfigured(str(exc)) from exc
    except Exception as exc:
        raise ApiError(
            "Could not load the index constituents. The universe lists come from "
            "niftyindices.com, which this server could not reach — check its "
            "network access and try again.",
            detail=str(exc),
        ) from exc
    if not tickers:
        raise ApiError("That universe resolved to zero stocks.")
    return tickers
