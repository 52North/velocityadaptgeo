from pathlib import Path

import pytest

from prompt_gen import seeds, stems

SEED = seeds.load("muenster_green_300m").text
FIRST_RUN = (Path(__file__).parent / "data" / "first_run_morphological.txt").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("candidate", FIRST_RUN)
def test_first_run_morphological_candidates_all_fail(candidate):
    # None of the 31 "morphological" paraphrases of the first run keeps to the seed's words.
    assert not stems.check(SEED, candidate).passed


def test_reports_the_synonyms_it_found():
    swapped = {w for c in FIRST_RUN for w in stems.check(SEED, c).new}
    assert {"generate", "routes", "determine", "create"} <= swapped


def test_seed_passes_against_itself():
    assert stems.check(SEED, SEED).passed


def test_inflection_and_modals_pass():
    candidate = (
        "Could you identify all areas in Münster that are within a 300-meter walking distance of public parks "
        "or forests large enough for recreation? Output a visualization that highlights these well-served areas "
        "and displays the walking distances from the green spaces in incremental intervals up to the 300-meter limit."
    )
    assert stems.check(SEED, candidate).passed


def test_derivations_pass():
    candidate = (
        "Identifying all areas in Münster that are within a 300-meter walkable distance of a public park or forest "
        "large enough for recreation, output a visualized highlighting of these well-served areas and a display of "
        "the walking distances from the green spaces in incremental intervals up to the 300-meter limit."
    )
    assert stems.check(SEED, candidate).passed


def test_deletion_fails_with_missing():
    result = stems.check(SEED, SEED.replace(" large enough for recreation", ""))
    assert result.new == ()
    assert result.missing == ("large", "enough", "recreation")


def test_spelling_change_is_not_morphological():
    assert stems.check(SEED, SEED.replace("Münster", "Muenster")).new == ("muenster",)


@pytest.mark.parametrize("a, b", [("walk", "walkabl"), ("visual", "visualiz"), ("identifi", "identif"), ("distanc", "distant")])
def test_same_family(a, b):
    assert stems.same_family(a, b)


@pytest.mark.parametrize("a, b", [("park", "parti"), ("area", "arena"), ("creat", "recreat"), ("map", "mapl")])
def test_different_family(a, b):
    assert not stems.same_family(a, b)
