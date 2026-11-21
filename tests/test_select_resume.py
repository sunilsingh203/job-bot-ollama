from pathlib import Path

import pytest

from jobbot.matcher.decide import decision_schema, select_resume
from jobbot.resumes.library import ResumeEntry, ResumeLibrary


@pytest.fixture
def lib():
    return ResumeLibrary(
        base_dir=Path("."),
        role_tracks={"sde": "", "java": "", "devops": ""},
        resumes=[
            ResumeEntry(id="sde_startup", file="a.pdf", roles=["sde"], company_type="startup"),
            ResumeEntry(id="sde_mnc", file="b.pdf", roles=["sde"], company_type="mnc"),
            ResumeEntry(id="java_any", file="c.pdf", roles=["java"], company_type="any"),
            ResumeEntry(id="devops_mnc", file="d.pdf", roles=["devops"], company_type="mnc"),
        ],
    )


def test_keeps_llm_choice_when_it_fits(lib):
    assert select_resume(lib, "sde", "mnc", "sde_mnc") == ("sde_mnc", None)


def test_overrides_wrong_company_variant(lib):
    rid, note = select_resume(lib, "sde", "startup", "sde_mnc")
    assert rid == "sde_startup"
    assert note and "sde_mnc" in note


def test_any_variant_used_when_no_exact(lib):
    assert select_resume(lib, "java", "startup", "java_any") == ("java_any", None)


def test_falls_back_to_other_variant_when_only_one_exists(lib):
    # Only an MNC devops resume exists; a startup devops job should still get it.
    assert select_resume(lib, "devops", "startup", "devops_mnc") == ("devops_mnc", None)


def test_unknown_company_type_keeps_any_role_match(lib):
    assert select_resume(lib, "sde", "unknown", "sde_startup") == ("sde_startup", None)


def test_unknown_track_keeps_valid_llm_choice(lib):
    assert select_resume(lib, "qa", "mnc", "java_any") == ("java_any", None)
    assert select_resume(lib, "qa", "mnc", "none") == (None, None)


def test_schema_constrains_enums(lib):
    props = decision_schema(lib)["properties"]
    assert props["resume_id"]["enum"] == [
        "sde_startup",
        "sde_mnc",
        "java_any",
        "devops_mnc",
        "none",
    ]
    assert props["role_track"]["enum"] == ["sde", "java", "devops", "none"]
