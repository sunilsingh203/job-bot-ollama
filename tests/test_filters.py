import pytest

from jobbot.config import MatchingSettings, Profile
from jobbot.matcher.filters import check_filters, required_experience
from jobbot.models import Job


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Requires 3+ years of experience in Java", 3),
        ("Experience: 2-4 yrs", 2),
        ("2 to 5 years experience in backend", 2),
        ("minimum 5 years of relevant experience", 5),
        ("5 plus years experience with AWS", 5),
        ("3+ years Java experience, 1+ year of AWS experience", 3),
        ("0-1 years of experience (freshers welcome)", 0),
        ("Founded 10 years ago, we serve 500 clients.", None),
        ("No experience numbers here.", None),
        ("40 years of experience", None),  # implausible -> ignored
    ],
)
def test_required_experience(text, expected):
    assert required_experience(text) == expected


@pytest.fixture
def profile():
    return Profile(total_experience_years=0.8)


@pytest.fixture
def settings():
    return MatchingSettings(blacklist_companies=["BadCorp"], blacklist_keywords=["unpaid"])


def test_passes_entry_level_job(profile, settings):
    job = Job(title="Java Developer", description="1-3 years of experience in Java.")
    r = check_filters(job, profile, settings)
    assert r.passed
    assert r.required_experience_years == 1


def test_rejects_too_much_experience(profile, settings):
    job = Job(title="DevOps Engineer", description="Requires 5+ years of experience.")
    r = check_filters(job, profile, settings)
    assert not r.passed
    assert "5+" in r.reason


def test_tolerance_boundary(profile, settings):
    # 0.8 + 2.0 tolerance = 2.8 -> "2+ years" passes, "3+ years" fails
    assert check_filters(
        Job(title="SDE", description="2+ years experience"), profile, settings
    ).passed
    assert not check_filters(
        Job(title="SDE", description="3+ years experience"), profile, settings
    ).passed


@pytest.mark.parametrize(
    "title",
    [
        "Senior Java Developer",
        "Sr. DevOps Engineer",
        "Tech Lead",
        "Solutions Architect",
        "Engineering Manager",
    ],
)
def test_rejects_senior_titles(profile, settings, title):
    assert not check_filters(Job(title=title, description="Java"), profile, settings).passed


def test_senior_word_inside_other_word_is_ok(profile, settings):
    # "Staffing" must not trigger the "staff" keyword; "Leader" must not trigger "lead"
    job = Job(title="Software Engineer - Staffing Platform", description="Java")
    assert check_filters(job, profile, settings).passed


def test_senior_titles_allowed_for_experienced_profile(settings):
    p = Profile(total_experience_years=6)
    assert check_filters(Job(title="Senior Java Developer", description="Java"), p, settings).passed


def test_blacklists(profile, settings):
    assert not check_filters(
        Job(title="SDE", company="BadCorp India", description="x"), profile, settings
    ).passed
    assert not check_filters(
        Job(title="SDE Intern", description="This is an unpaid role"), profile, settings
    ).passed
