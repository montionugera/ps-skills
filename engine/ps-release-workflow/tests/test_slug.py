"""Slugification: title → kebab-slug."""
from lib.slug import slugify


def test_simple():
    assert slugify("Add fee cap") == "add-fee-cap"


def test_punctuation_stripped():
    assert slugify("MT5: don't break!") == "mt5-don-t-break"


def test_collapses_whitespace_and_dashes():
    assert slugify("  too   many---dashes  ") == "too-many-dashes"


def test_truncates_to_max_length():
    assert len(slugify("a" * 100, max_len=20)) <= 20


def test_lowercase():
    assert slugify("UPPERCASE TITLE") == "uppercase-title"


def test_empty_raises():
    import pytest
    from lib.slug import SlugError
    with pytest.raises(SlugError):
        slugify("")
