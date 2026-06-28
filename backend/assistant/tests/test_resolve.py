"""FK-resolution task — resolve_reference (pure ranking) + resolve_field (RBAC + suggestions)."""

import pytest

from assistant.tests.fakes import FakeProvider, make_user

from assistant.module_interface import Candidate, ResourceSpec, get_resource, register_resource
from assistant import resolve as resolve_mod
from assistant.resolve import (
    AMBIGUOUS,
    MISSING,
    RESOLVED,
    resolve_field,
    resolve_reference,
)


def _c(cid, match_text, label=None):
    return Candidate(id=cid, match_text=match_text, label=label or match_text)


# ---------------------------------------------------------------------------
# resolve_reference — pure, no DB / no model
# ---------------------------------------------------------------------------

def test_zero_candidates_is_missing():
    res = resolve_reference("credit_card_id", "Mellat", [])
    assert res.status == MISSING
    assert res.chosen is None


def test_single_candidate_is_resolved():
    res = resolve_reference("credit_card_id", "anything", [_c(12, "Mellat", "Mellat — •••• 4821")])
    assert res.status == RESOLVED
    assert res.chosen == {"id": 12, "label": "Mellat — •••• 4821"}
    assert res.alternatives == []


def test_two_candidates_one_exact_match_resolves_exact():
    cands = [_c(1, "Ali Rezaei"), _c(2, "ali rezaei")]  # both names equal the query case-insensitively
    # Use a query that exactly matches only ONE candidate's match_text.
    cands = [_c(1, "ACME Holdings"), _c(2, "ACME")]
    res = resolve_reference("customer_id", "acme", cands)
    assert res.status == RESOLVED
    assert res.chosen["id"] == 2  # the exact case-insensitive name match
    assert [a["id"] for a in res.alternatives] == [1]


def test_two_candidates_no_exact_match_is_ambiguous():
    cands = [_c(7, "Bank Mellat"), _c(9, "Mellat Pasargad")]
    res = resolve_reference("credit_card_id", "mellat", cands)
    assert res.status == AMBIGUOUS
    assert res.chosen["id"] == 7  # first candidate is the default
    assert [a["id"] for a in res.alternatives] == [9]


def test_multiple_exact_matches_is_ambiguous():
    cands = [_c(1, "ACME"), _c(2, "acme"), _c(3, "Other")]
    res = resolve_reference("customer_id", "ACME", cands)
    assert res.status == AMBIGUOUS
    assert res.chosen["id"] == 1
    assert len(res.alternatives) == 2


# ---------------------------------------------------------------------------
# resolve_field — orchestration, RBAC, create-suggestion
# ---------------------------------------------------------------------------

_READ = "test:things:read"
_CREATE = "test:things:create"


@pytest.fixture
def test_resource():
    """Register/restore a throwaway resource keyed 'test_thing'."""
    saved = get_resource("test_thing")
    holder = {}

    def install(candidates):
        provider = FakeProvider(candidates)
        holder["provider"] = provider
        register_resource(ResourceSpec(
            key="test_thing",
            read_permission=_READ,
            provider=provider,
            create_permission=_CREATE,
            create_endpoint="/test/things",
            suggestion_from=lambda raw, slots: {"name": raw},
        ))
        return provider

    yield install
    if saved is not None:
        register_resource(saved)
    else:
        resolve_mod.get_resource  # no-op; leave the test key registered harmlessly


def test_explicit_id_wins_and_skips_search(test_resource):
    provider = test_resource([_c(99, "should not be returned")])
    user = make_user([_READ])
    res = resolve_field(None, user, field="customer_id", resource_key="test_thing",
                        raw_text="ignored", slots={}, explicit_id=5)
    assert res.status == RESOLVED
    assert res.note == "explicit_id"
    assert res.chosen == {"id": 5, "label": None}
    assert provider.calls == []  # provider NOT called


def test_no_read_permission_is_missing_no_access(test_resource):
    test_resource([_c(1, "Ali")])
    user = make_user([])  # lacks test:things:read
    res = resolve_field(None, user, field="customer_id", resource_key="test_thing",
                        raw_text="Ali", slots={})
    assert res.status == MISSING
    assert res.note == "no_access"


def test_unknown_resource_is_missing():
    user = make_user([_READ])
    res = resolve_field(None, user, field="customer_id", resource_key="does_not_exist",
                        raw_text="x", slots={})
    assert res.status == MISSING
    assert res.note == "unknown_resource"


def test_missing_with_registered_create_resource_gets_suggestion(test_resource):
    test_resource([])  # no hits -> missing
    user = make_user([_READ, _CREATE])
    res = resolve_field(None, user, field="customer_id", resource_key="test_thing",
                        raw_text="Ali Rezaei", slots={})
    assert res.status == MISSING
    assert res.create_suggestion is not None
    assert res.create_suggestion["endpoint"] == "/test/things"
    assert res.create_suggestion["payload"] == {"name": "Ali Rezaei"}


def test_resolved_when_single_hit(test_resource):
    provider = test_resource([_c(12, "Mellat", "Mellat — •••• 4821")])
    user = make_user([_READ])
    res = resolve_field(None, user, field="credit_card_id", resource_key="test_thing",
                        raw_text="Mellat", slots={})
    assert res.status == RESOLVED
    assert res.chosen == {"id": 12, "label": "Mellat — •••• 4821"}
    assert provider.calls and provider.calls[0]["query"] == "Mellat"
