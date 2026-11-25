import unittest

from app.categorizer import CATEGORIES, categorize


class CategorizerTests(unittest.TestCase):
    def test_common_indian_vendors(self):
        cases = {
            "Swiggy": "Food & Dining",
            "ZOMATO ORDER": "Food & Dining",
            "Uber India": "Transport",
            "Ola": "Transport",
            "Amazon Pay": "Shopping",
            "Apollo Pharmacy": "Health",
            "Jio Recharge": "Bills & Utilities",
            "IRCTC": "Travel",
            "Netflix": "Entertainment",
        }
        for vendor, expected in cases.items():
            with self.subTest(vendor=vendor):
                self.assertEqual(categorize(vendor), expected)

    def test_longest_keyword_wins(self):
        self.assertEqual(categorize("Swiggy Instamart"), "Groceries")

    def test_short_keywords_need_a_whole_word(self):
        # "cola" contains "ola" but is not the cab company.
        self.assertNotEqual(categorize("Cola Corner Stall"), "Transport")
        self.assertEqual(categorize("Ola Cabs"), "Transport")

    def test_devanagari_vendors(self):
        self.assertEqual(categorize("श्री बेकरी"), "Food & Dining")
        self.assertEqual(categorize("किराणा स्टोअर"), "Groceries")
        self.assertEqual(categorize("मेडिकल स्टोअर"), "Health")

    def test_unknown_vendor_is_other(self):
        self.assertEqual(categorize("Ramesh Traders"), "Other")
        self.assertEqual(categorize(""), "Other")

    def test_hint_used_only_when_no_rule_matches(self):
        self.assertEqual(categorize("Ramesh Traders", hint="Shopping"), "Shopping")
        self.assertEqual(categorize("Swiggy", hint="Shopping"), "Food & Dining")

    def test_invalid_hint_ignored(self):
        self.assertEqual(categorize("Ramesh Traders", hint="Crypto"), "Other")

    def test_every_rule_category_is_known(self):
        from app.categorizer import RULES
        self.assertTrue(set(RULES) <= set(CATEGORIES))


if __name__ == "__main__":
    unittest.main()
