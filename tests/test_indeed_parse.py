from pathlib import Path

from jobbot.config import Search
from jobbot.platforms.indeed.parse import (
    is_challenge,
    is_signin,
    parse_description,
    parse_search_page,
)
from jobbot.platforms.indeed.scanner import search_url

FIXTURES = Path(__file__).parent / "fixtures" / "indeed"
BASE = "https://in.indeed.com"


def test_parse_real_search_page_json():
    page = parse_search_page((FIXTURES / "search_page.html").read_text(encoding="utf-8"), BASE)
    assert page.source == "json"
    assert page.logged_in is False
    assert len(page.listings) == 3

    first = page.listings[0].job
    assert first.job_key == "f50e902fd858bbc1"
    assert first.title == "Full Stack Developer"
    assert first.company == "SPARC PVT LTD"
    assert first.easy_apply is True
    assert first.platform == "indeed"
    assert first.url == f"{BASE}/viewjob?jk=f50e902fd858bbc1"
    assert first.posted_at and len(first.posted_at) == 10  # ISO date

    second = page.listings[1]
    assert second.job.easy_apply is False
    assert second.job.salary and "5.50" in second.job.salary
    assert second.snippet  # HTML snippet converted to text
    assert "<li" not in second.snippet


DOM_PAGE = """
<html><body><ul>
  <li><div class="job_seen_beacon">
    <h2 class="jobTitle"><a data-jk="aaa111"><span>Java Developer</span></a></h2>
    <span data-testid="company-name">Acme Corp</span>
    <div data-testid="text-location">Remote</div>
    <span>Easily apply</span>
  </div></li>
  <li><div class="job_seen_beacon">
    <h2 class="jobTitle"><a data-jk="bbb222"><span>DevOps Engineer</span></a></h2>
    <span data-testid="company-name">Beta Labs</span>
    <div data-testid="text-location">Pune, Maharashtra</div>
  </div></li>
  <li><a data-jk="aaa111">duplicate link to the same job</a></li>
</ul></body></html>
"""


def test_dom_fallback_when_json_missing():
    page = parse_search_page(DOM_PAGE, BASE)
    assert page.source == "dom"
    assert [x.job.job_key for x in page.listings] == ["aaa111", "bbb222"]
    a, b = (x.job for x in page.listings)
    assert (a.title, a.company, a.location, a.easy_apply, a.remote) == (
        "Java Developer",
        "Acme Corp",
        "Remote",
        True,
        True,
    )
    assert (b.easy_apply, b.remote) == (False, False)


def test_broken_json_falls_back_to_dom():
    html = 'window.mosaic.providerData["mosaic-provider-jobcards"]={not json' + DOM_PAGE
    assert parse_search_page(html, BASE).source == "dom"


def test_parse_description():
    html = """<div id="jobDescriptionText"><p>We need a <b>Java</b> dev.</p>
      <ul><li>Spring Boot</li><li>3+ years experience</li></ul></div>"""
    text = parse_description(html)
    assert text is not None
    assert "We need a Java dev." in text
    assert "- Spring Boot" in text
    assert "- 3+ years experience" in text
    assert parse_description("<div>nothing here</div>") is None


def test_challenge_and_signin_detection():
    assert is_challenge("Just a moment...", "")
    assert is_challenge("Indeed", "<h1>Additional Verification Required</h1>")
    assert not is_challenge("Java Developer Jobs | Indeed", "<html>jobs</html>")
    assert is_signin("https://secure.indeed.com/auth?continue=x")
    assert not is_signin("https://in.indeed.com/jobs?q=java")


def test_search_url():
    s = Search(name="x", query="java developer", location="India", fromage=3)
    assert search_url(BASE, s, 0) == f"{BASE}/jobs?q=java+developer&l=India&sort=date&fromage=3"
    assert search_url(BASE, s, 2).endswith("&start=20")
    s2 = Search(
        name="y",
        query="devops",
        location="Remote",
        fromage=None,
        extra_params={"sc": "0kf:attr(DSQF7);"},
    )
    url = search_url(BASE, s2, 0)
    assert "fromage" not in url and "sc=0kf%3Aattr%28DSQF7%29%3B" in url
