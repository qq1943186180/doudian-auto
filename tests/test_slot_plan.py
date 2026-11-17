"""Slot plans: how many fixed image slots a revision actually replaces.

The writer replaces images by matching the old one, so a listing with two detail images
has no third and fourth source picture. These tests pin the plan's defaults (a baseline
without one behaves exactly like the old nine-slot contract), its validation, and the
prefix semantics the readback comparison uses.
"""
import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_batch_editor import _plan_from_slots


def test_a_baseline_without_a_plan_keeps_the_full_nine_slots():
    # Every baseline written before this contract must keep its old meaning: five mains
    # and four details. Nothing that used to be compared stops being compared.
    plan = batch._slot_plan({'doudian_baseline': {}})
    assert plan == {'mains': 5, 'details': 4}
    assert batch._expected_slots(plan) == {
        'mains:1', 'mains:2', 'mains:3', 'mains:4', 'mains:5',
        'details:1', 'details:2', 'details:3', 'details:4'}


def test_a_recorded_plan_is_used_verbatim():
    plan = batch._slot_plan({'slot_plan': {'mains': 5, 'details': 2}})
    assert batch._expected_slots(plan) == {
        'mains:1', 'mains:2', 'mains:3', 'mains:4', 'mains:5',
        'details:1', 'details:2'}


@pytest.mark.parametrize('plan', [
    {'mains': 0, 'details': 2},      # nothing to replace
    {'mains': 6, 'details': 2},      # beyond the five-main cap
    {'mains': 5, 'details': 0},
    {'mains': 5, 'details': 5},      # beyond the four-detail cap
    {'mains': True, 'details': 2},   # bool is not a slot count
    {'mains': 5, 'details': None},
])
def test_an_impossible_plan_stops_instead_of_guessing(plan):
    with pytest.raises(DoudianError) as caught:
        batch._slot_plan({'slot_plan': plan})
    assert caught.value.code == 'invalid_slot_plan'


def test_the_plan_comes_from_the_listing_itself():
    snapshot = {'mains': ['m'] * 5, 'details': ['d'] * 2}
    assert batch._plan_for_snapshot(snapshot) == {'mains': 5, 'details': 2}
    # More details than the writer replaces are clipped, not rejected: the extra images
    # stay untouched because the replacement is per slot.
    assert batch._plan_for_snapshot({'mains': ['m'] * 5, 'details': ['d'] * 15}) == {
        'mains': 5, 'details': 4}


@pytest.mark.parametrize('snapshot', [
    {'mains': [], 'details': ['d']},
    {'mains': ['m'] * 6, 'details': ['d']},
    {'mains': ['m'], 'details': []},
])
def test_a_listing_with_no_slots_stops(snapshot):
    with pytest.raises(DoudianError) as caught:
        batch._plan_for_snapshot(snapshot)
    assert caught.value.code == 'writer_image_slots_incomplete'


def test_slot_sets_must_be_contiguous_and_within_the_cap():
    assert _plan_from_slots({'mains:1', 'mains:2', 'details:1'}) == {'mains': 2, 'details': 1}
    with pytest.raises(DoudianError):
        _plan_from_slots({'mains:1', 'mains:3', 'details:1'})   # hole in the numbering
    with pytest.raises(DoudianError):
        _plan_from_slots({*(f'mains:{i}' for i in range(1, 7)), 'details:1'})


def test_readback_compares_only_the_planned_prefix(monkeypatch):
    # Two detail slots: the first two must match the targets and the rest must be the
    # baseline's own images. A shorter plan must not silently skip the tail comparison.
    monkeypatch.setattr('doudian_auto.workflow.compare_protected', lambda *a, **k: None)
    plan = {'mains': 5, 'details': 2}
    mappings = ([{'slot': f'mains:{i}', 'remote_key': f'key-main-{i}'} for i in range(1, 6)] +
                [{'slot': f'details:{i}', 'remote_key': f'key-det-{i}'} for i in range(1, 3)])
    before = {'mains': [f'https://p3.example/ecom-shop-material/key-main-old-{i}' for i in range(1, 6)],
              'details': ['https://p3.example/ecom-shop-material/key-det-old-1',
                          'https://p3.example/ecom-shop-material/key-det-old-2',
                          'https://p3.example/ecom-shop-material/key-tail-1']}
    after = {'title': '同标题', 'draft_loaded': False, 'rejected': False,
             'mains': [f'https://p3.example/ecom-shop-material/key-main-{i}' for i in range(1, 6)],
             'details': ['https://p3.example/ecom-shop-material/key-det-1',
                         'https://p3.example/ecom-shop-material/key-det-2',
                         'https://p3.example/ecom-shop-material/key-tail-1']}
    assert batch._matches_doudian_target(before, after, '同标题', mappings, plan) is True
    # The untouched tail changing is still a mismatch.
    changed_tail = {**after, 'details': after['details'][:2] +
                    ['https://p3.example/ecom-shop-material/key-tail-2']}
    assert batch._matches_doudian_target(before, changed_tail, '同标题', mappings, plan) is False
