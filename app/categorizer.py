"""Rule-based spending categorizer.

Rules run before any AI call: they are free, instant, deterministic and easy to
test. Keywords cover English plus common Hindi/Marathi (Devanagari) words so
vendors printed in other scripts still match. When several categories match,
the category with the *longest* matching keyword wins, so "swiggy instamart"
is Groceries (instamart) rather than Food & Dining (swiggy).
"""
from __future__ import annotations

import re
from typing import Optional

CATEGORIES = (
    "Food & Dining",
    "Groceries",
    "Transport",
    "Travel",
    "Shopping",
    "Bills & Utilities",
    "Health",
    "Entertainment",
    "Education",
    "Other",
)

DEFAULT_CATEGORY = "Other"

RULES: dict[str, tuple[str, ...]] = {
    "Food & Dining": (
        "swiggy", "zomato", "restaurant", "cafe", "dominos", "pizza", "burger",
        "mcdonalds", "kfc", "starbucks", "chai", "bakery", "biryani", "dhaba",
        "canteen", "mess", "eatery", "juice", "icecream", "sweets", "tiffin",
        "रेस्टॉरंट", "रेस्टोरेंट", "हॉटेल", "बेकरी", "चहा", "चाय", "ढाबा", "मिठाई",
    ),
    "Groceries": (
        "bigbasket", "blinkit", "zepto", "dmart", "instamart", "jiomart", "kirana",
        "supermarket", "grocery", "provision", "vegetables", "fruits", "milk",
        "reliance fresh", "more retail", "nature's basket",
        "किराणा", "किराना", "भाजी", "सब्जी", "दूध", "बाजार",
    ),
    "Transport": (
        "uber", "ola", "rapido", "metro", "fastag", "petrol", "diesel", "fuel",
        "parking", "indian oil", "bharat petroleum", "hp petrol", "auto", "cab",
        "पेट्रोल", "डिझेल", "मेट्रो", "रिक्षा", "टॅक्सी",
    ),
    "Travel": (
        "irctc", "makemytrip", "goibibo", "redbus", "indigo", "air india", "yatra",
        "railway", "flight", "airlines", "booking.com", "oyo",
        "रेल्वे", "विमान",
    ),
    "Shopping": (
        "amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "mall",
        "fashion", "clothing", "electronics", "croma", "decathlon", "lifestyle",
        "garments", "footwear", "कपडे", "कपड़े", "दुकान",
    ),
    "Bills & Utilities": (
        "jio", "airtel", "vodafone", "bsnl", "electricity", "mseb", "mahavitaran",
        "tata power", "bescom", "recharge", "broadband", "water bill", "gas",
        "mahanagar", "postpaid", "prepaid", "dth", "tatasky", "insurance", "rent",
        "बिजली", "वीज", "रिचार्ज", "गैस", "भाडे", "किराया",
    ),
    "Health": (
        "apollo", "pharmacy", "medplus", "1mg", "pharmeasy", "hospital", "clinic",
        "diagnostic", "chemist", "medical", "dental", "pathology", "lab",
        "मेडिकल", "औषध", "दवा", "दवाखाना", "रुग्णालय", "अस्पताल",
    ),
    "Entertainment": (
        "netflix", "bookmyshow", "spotify", "hotstar", "pvr", "inox", "youtube",
        "prime video", "cinema", "movie", "gaming", "steam", "sonyliv",
        "चित्रपट", "सिनेमा",
    ),
    "Education": (
        "school", "college", "tuition", "udemy", "coursera", "byjus", "unacademy",
        "fees", "books", "stationery", "university", "coaching", "exam",
        "विद्यालय", "शाळा", "महाविद्यालय", "पुस्तक", "फीस",
    ),
}

_SPLIT = re.compile(r"[\s\-_/.,&@()|:+*#]+")
_MIN_SUBSTRING_LEN = 5  # shorter keywords must match a whole word ("ola" != "cola")


def _normalise(text: str) -> str:
    return " ".join(t for t in _SPLIT.split(text.casefold()) if t)


def _matches(keyword: str, normalised: str, tokens: set[str]) -> bool:
    if " " in keyword:
        return keyword in normalised
    if keyword in tokens:
        return True
    if len(keyword) >= _MIN_SUBSTRING_LEN:
        return any(keyword in token for token in tokens)
    return False


def categorize(vendor: str, hint: Optional[str] = None) -> str:
    """Return a category for a vendor name.

    ``hint`` is an optional suggestion (e.g. from the AI extractor). It is only
    used when no rule matches, and only if it is one of the known categories.
    """
    normalised = _normalise(vendor or "")
    tokens = set(normalised.split())

    best_category, best_len = None, 0
    for category, keywords in RULES.items():
        for keyword in keywords:
            if len(keyword) > best_len and _matches(keyword.casefold(), normalised, tokens):
                best_category, best_len = category, len(keyword)

    if best_category:
        return best_category
    if hint in CATEGORIES:
        return hint  # type: ignore[return-value]
    return DEFAULT_CATEGORY
