import unittest
from datetime import date
from decimal import Decimal

from app.budget import analyze, format_inr, pick_month

TODAY = date(2026, 11, 15)  # mid-month so projections apply


def exp(vendor, amount, category, day="2026-11-05"):
    return {"vendor": vendor, "amount": amount, "category": category, "date": day}


class FormatTests(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(Decimal("999")), "₹999")
        self.assertEqual(format_inr(Decimal("1234")), "₹1,234")
        self.assertEqual(format_inr(Decimal("123456")), "₹1,23,456")
        self.assertEqual(format_inr(Decimal("12345678.5")), "₹1,23,45,678.50")


class AnalyzeTests(unittest.TestCase):
    def test_totals_and_status(self):
        expenses = [exp("Swiggy", 500, "Food & Dining"), exp("Zomato", 800, "Food & Dining"),
                    exp("Uber", 200, "Transport")]
        result = analyze(expenses, {"Food & Dining": 1000, "Transport": 1000}, "2026-11", TODAY)
        rows = {r["category"]: r for r in result["categories"]}
        self.assertEqual(result["total_spent"], 1500.0)
        self.assertEqual(result["total_budget"], 2000.0)
        self.assertEqual(rows["Food & Dining"]["status"], "over")
        self.assertEqual(rows["Food & Dining"]["percent"], 130.0)
        self.assertEqual(rows["Transport"]["status"], "ok")
        self.assertEqual(rows["Transport"]["remaining"], 800.0)

    def test_warning_at_eighty_percent(self):
        result = analyze([exp("Uber", 850, "Transport")], {"Transport": 1000}, "2026-11", TODAY)
        self.assertEqual(result["categories"][0]["status"], "warning")
        self.assertTrue(any(a["level"] == "warning" for a in result["alerts"]))

    def test_no_budget_status(self):
        result = analyze([exp("Uber", 100, "Transport")], {}, "2026-11", TODAY)
        self.assertEqual(result["categories"][0]["status"], "no_budget")
        self.assertIsNone(result["total_budget"])

    def test_budget_without_spending_still_listed(self):
        result = analyze([], {"Health": 500}, "2026-11", TODAY)
        self.assertEqual(result["categories"][0]["spent"], 0.0)
        self.assertEqual(result["categories"][0]["status"], "ok")

    def test_month_filter_excludes_other_months(self):
        expenses = [exp("A", 100, "Other", "2026-10-30"), exp("B", 50, "Other", "2026-11-01")]
        self.assertEqual(analyze(expenses, {}, "2026-11", TODAY)["total_spent"], 50.0)

    def test_undated_expenses_count_in_viewed_month(self):
        self.assertEqual(analyze([exp("A", 70, "Other", None)], {}, "2026-11", TODAY)["total_spent"], 70.0)

    def test_projection_alert_for_current_month(self):
        # 600 spent by day 15 of a 30-day month -> projects 1200 > 1000 budget
        result = analyze([exp("Uber", 600, "Transport")], {"Transport": 1000}, "2026-11", TODAY)
        self.assertEqual(result["projected_total"], 1200.0)
        self.assertTrue(any(a["level"] == "projection" for a in result["alerts"]))

    def test_no_projection_for_past_month(self):
        result = analyze([exp("Uber", 600, "Transport", "2026-09-10")], {"Transport": 1000}, "2026-09", TODAY)
        self.assertIsNone(result["projected_total"])
        self.assertFalse(any(a["level"] == "projection" for a in result["alerts"]))

    def test_suggestion_names_dominant_vendor_and_headroom(self):
        expenses = [exp("Swiggy", 900, "Food & Dining"), exp("Chai Point", 200, "Food & Dining"),
                    exp("Metro", 100, "Transport")]
        result = analyze(expenses, {"Food & Dining": 800, "Transport": 2000}, "2026-11", TODAY)
        text = " ".join(result["suggestions"])
        self.assertIn("Swiggy", text)
        self.assertIn("Transport has", text)

    def test_top_vendors_merge_case_insensitively(self):
        expenses = [exp("Swiggy", 100, "Food & Dining"), exp("SWIGGY", 150, "Food & Dining"),
                    exp("Uber", 50, "Transport")]
        top = analyze(expenses, {}, "2026-11", TODAY)["top_vendors"]
        self.assertEqual(top[0]["total"], 250.0)
        self.assertEqual(top[0]["count"], 2)

    def test_decimal_precision(self):
        expenses = [exp("A", 0.1, "Other"), exp("B", 0.2, "Other")]
        self.assertEqual(analyze(expenses, {}, "2026-11", TODAY)["total_spent"], 0.3)

    def test_pick_month_prefers_latest_dated(self):
        expenses = [exp("A", 1, "Other", "2026-08-01"), exp("B", 1, "Other", "2026-10-09")]
        self.assertEqual(pick_month(expenses, TODAY), "2026-10")
        self.assertEqual(pick_month([], TODAY), "2026-11")


if __name__ == "__main__":
    unittest.main()
