"""Monthly budget analysis.

Pure functions (no I/O) so the decision logic is easy to unit test.
Money is handled with Decimal and converted to float only at the edge.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional

WARNING_RATIO = Decimal("0.8")  # warn when 80% of a category budget is used
TWO_PLACES = Decimal("0.01")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> float:
    return float(value.quantize(TWO_PLACES, ROUND_HALF_UP))


def format_inr(value: Decimal) -> str:
    """Format with Indian digit grouping, e.g. 1234567 -> '₹12,34,567'."""
    value = value.quantize(TWO_PLACES, ROUND_HALF_UP)
    whole, _, frac = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    text = whole if frac == "00" else f"{whole}.{frac}"
    return f"{'-' if value < 0 else ''}₹{text}"


def _in_month(expense: Mapping[str, Any], month: str) -> bool:
    # Expenses without a date are counted in whichever month is being viewed.
    day = expense.get("date")
    return not day or str(day)[:7] == month


def pick_month(expenses: Iterable[Mapping[str, Any]], today: date) -> str:
    """Latest month that has dated expenses, else the current month."""
    months = sorted({str(e["date"])[:7] for e in expenses if e.get("date")})
    return months[-1] if months else today.strftime("%Y-%m")


def analyze(
    expenses: list[Mapping[str, Any]],
    budgets: Mapping[str, float],
    month: Optional[str] = None,
    today: Optional[date] = None,
) -> dict:
    today = today or date.today()
    month = month or pick_month(expenses, today)
    in_scope = [e for e in expenses if _in_month(e, month)]

    spent: dict[str, Decimal] = defaultdict(Decimal)
    vendors: dict[str, dict] = {}
    vendor_by_category: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for e in in_scope:
        amount, category = _d(e["amount"]), e["category"]
        spent[category] += amount
        key = str(e["vendor"]).casefold()
        entry = vendors.setdefault(key, {"vendor": e["vendor"], "total": Decimal(0), "count": 0})
        entry["total"] += amount
        entry["count"] += 1
        vendor_by_category[category][e["vendor"]] += amount

    # Only extrapolate for the month in progress.
    is_current = month == today.strftime("%Y-%m")
    days_in_month = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
    elapsed = today.day if is_current else None

    rows, alerts = [], []
    categories = sorted(set(spent) | set(budgets), key=lambda c: (-spent.get(c, Decimal(0)), c))
    for category in categories:
        s = spent.get(category, Decimal(0))
        b = _d(budgets[category]) if budgets.get(category) else None
        projected = s / elapsed * days_in_month if elapsed else None

        if b is None:
            status, percent, remaining = "no_budget", None, None
        else:
            ratio = s / b
            percent, remaining = round(float(ratio) * 100, 1), b - s
            status = "over" if s > b else "warning" if ratio >= WARNING_RATIO else "ok"

        rows.append({
            "category": category,
            "spent": money(s),
            "budget": money(b) if b is not None else None,
            "percent": percent,
            "remaining": money(remaining) if remaining is not None else None,
            "status": status,
            "projected": money(projected) if projected is not None else None,
        })

        if status == "over":
            alerts.append({"level": "over", "category": category,
                           "message": f"{category} is {format_inr(s - b)} over budget ({percent:.0f}% used)."})
        elif status == "warning":
            alerts.append({"level": "warning", "category": category,
                           "message": f"{category} has used {percent:.0f}% of its budget. {format_inr(remaining)} left."})
        if status in ("ok", "warning") and b is not None and projected is not None and projected > b:
            alerts.append({"level": "projection", "category": category,
                           "message": f"At this pace {category} will reach {format_inr(projected)} by month end, "
                                      f"{format_inr(projected - b)} over budget."})

    total_spent = sum(spent.values(), Decimal(0))
    total_budget = sum((_d(v) for v in budgets.values() if v), Decimal(0))
    projected_total = total_spent / elapsed * days_in_month if elapsed else None

    return {
        "month": month,
        "currency": "INR",
        "transaction_count": len(in_scope),
        "total_spent": money(total_spent),
        "total_budget": money(total_budget) if total_budget else None,
        "projected_total": money(projected_total) if projected_total is not None else None,
        "categories": rows,
        "top_vendors": [
            {"vendor": v["vendor"], "total": money(v["total"]), "count": v["count"]}
            for v in sorted(vendors.values(), key=lambda v: -v["total"])[:5]
        ],
        "alerts": alerts,
        "suggestions": _suggestions(rows, spent, vendor_by_category),
    }


def _suggestions(rows: list[dict], spent: Mapping[str, Decimal],
                 vendor_by_category: Mapping[str, Mapping[str, Decimal]]) -> list[str]:
    """Context-aware tips: what is over, who drives it, and where there is room."""
    tips: list[str] = []
    headroom = sorted(
        (r for r in rows if r["status"] == "ok" and r["remaining"]),
        key=lambda r: -r["remaining"],
    )
    for row in (r for r in rows if r["status"] == "over"):
        category, overshoot = row["category"], _d(row["spent"]) - _d(row["budget"])
        vendor, vendor_total = max(vendor_by_category[category].items(), key=lambda kv: kv[1])
        share = round(float(vendor_total / spent[category]) * 100)
        if len(vendor_by_category[category]) > 1 and share >= 40:
            tips.append(f"{vendor} makes up {share}% of your {category} spending. "
                        f"Trimming it is the quickest way to recover {format_inr(overshoot)}.")
        else:
            tips.append(f"Cut {format_inr(overshoot)} from {category} or raise its budget.")
        if headroom:
            donor = headroom[0]
            move = min(overshoot, _d(donor["remaining"]))
            tips.append(f"{donor['category']} has {format_inr(_d(donor['remaining']))} unused. "
                        f"Moving {format_inr(move)} would ease {category}.")
    return tips[:5]
