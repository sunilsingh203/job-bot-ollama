import pytest

from jobbot.matcher.company_type import (
    in_mnc_list,
    normalize_company,
    parse_company_size,
    resolve_company_type,
)

MNCS = ["Accenture", "Tata Consultancy Services", "TCS", "Infosys", "Amazon", "SAP"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Accenture Solutions Pvt Ltd", "accenture"),
        ("Infosys Limited", "infosys"),
        ("Tata Consultancy Services", "tata consultancy"),
        ("Amazon Development Centre (India) Pvt. Ltd.", "amazon development centre"),
    ],
)
def test_normalize(name, expected):
    assert normalize_company(name) == expected


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        ("Accenture Solutions Pvt Ltd", True),
        ("TCS", True),
        ("Tata Consultancy Services Limited", True),
        ("Infosys BPM", True),
        ("Amazon Web Services India", True),
        ("SAP Labs India", True),
        ("Sapient Startups", False),  # "sap" must match whole word only
        ("TCSX Labs", False),
        ("CloudNest Labs", False),
        ("", False),
    ],
)
def test_in_mnc_list(company, expected):
    assert in_mnc_list(company, MNCS) is expected


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("10,000+ employees", 10000),
        ("1001 to 5000", 1001),
        ("51-200 employees", 51),
        (None, None),
        ("unknown", None),
    ],
)
def test_parse_company_size(size, expected):
    assert parse_company_size(size) == expected


def test_resolve_order():
    assert resolve_company_type("Infosys", "11-50", MNCS, 1000) == ("mnc", "mnc_list")
    assert resolve_company_type("Acme", "5,001-10,000", MNCS, 1000) == ("mnc", "company_size")
    assert resolve_company_type("Acme", "11-50 employees", MNCS, 1000) == (
        "startup",
        "company_size",
    )
    assert resolve_company_type("Acme", None, MNCS, 1000) == ("unknown", "unknown")
