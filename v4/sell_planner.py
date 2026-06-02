"""Decide which duplicate vehicles are safe to sell -- pure, side-effect-free logic.

The risky half of "sell duplicates" is deciding WHAT to sell. Keep that here, fully
unit-tested and independent of any pad/recognition, so the runner only has to execute
a vetted plan. Hard safety rules (encoded below, not optional):
  - NEVER sell the current vehicle (当前车辆) or a favorited car (收藏).
  - Keep at least `keep_per_model` copies of every model (protected copies count).
  - Only ever propose selling EXTRA, non-protected copies of a model you own >1 of.
A car you own exactly one of is never sold.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VehicleCard:
    name: str                 # normalized car name, the duplicate key
    is_current: bool = False  # 当前车辆 -- never sold
    is_favorite: bool = False # 收藏 -- never sold
    card_id: str = ""         # opaque locator the runner uses to revisit the card
    rarity: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def protected(self) -> bool:
        return self.is_current or self.is_favorite


def plan_duplicate_sales(cards, keep_per_model: int = 1) -> list:
    """Return the list of VehicleCards safe to sell (extra, non-protected copies).

    keep_per_model: minimum copies to keep per model (protected copies count toward it).
    """
    keep_per_model = max(1, int(keep_per_model))
    by_name: dict[str, list] = {}
    for card in cards:
        name = (getattr(card, "name", "") or "").strip()
        if not name:
            continue
        by_name.setdefault(name, []).append(card)

    to_sell = []
    for name, group in by_name.items():
        if len(group) <= keep_per_model:
            continue  # not enough copies to have any extra
        protected = [c for c in group if c.protected]
        others = [c for c in group if not c.protected]
        # keep all protected, then fill up to keep_per_model with non-protected copies
        keep_others = max(0, keep_per_model - len(protected))
        to_sell.extend(others[keep_others:])  # the surplus non-protected copies
    return to_sell


def summarize_plan(cards, keep_per_model: int = 1) -> dict:
    """Human-facing dry-run summary: counts per model + what would be sold/kept."""
    sell = plan_duplicate_sales(cards, keep_per_model)
    sell_ids = {id(c) for c in sell}
    by_name: dict[str, dict] = {}
    for card in cards:
        name = (getattr(card, "name", "") or "").strip()
        if not name:
            continue
        entry = by_name.setdefault(name, {"owned": 0, "sell": 0, "protected": 0})
        entry["owned"] += 1
        if id(card) in sell_ids:
            entry["sell"] += 1
        if card.protected:
            entry["protected"] += 1
    return {
        "total_cards": len(cards),
        "total_to_sell": len(sell),
        "by_model": {k: v for k, v in by_name.items() if v["sell"] > 0},
    }
