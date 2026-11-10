"""Commander routing and attribute-write guards.

These cover the decisions that must not silently go wrong: a verified product is never
re-saved, a product missing real facts is never guessed, and the attribute writer refuses
the control shapes it cannot verify.
"""

import json

import pytest

from doudian_auto import attributes, commander
from doudian_auto.errors import DoudianError


def row(**kw):
    base = {'product_id': '1', 'state': 'blocked', 'submission_state': 'not_attempted',
            'last_error': None, 'title': 't'}
    base.update(kw)
    return base


def test_verified_is_skipped_not_resaved():
    outcome, _ = commander.decide(row(state='verified'))
    assert outcome == commander.SKIP_VERIFIED
    outcome, _ = commander.decide(row(submission_state='verified_by_readback'))
    assert outcome == commander.SKIP_VERIFIED


@pytest.mark.parametrize('submission', ['unknown', 'accepted'])
def test_unconfirmed_submission_only_reads_back(submission):
    # Re-sending here risks a duplicate listing; the only safe action is a read.
    outcome, _ = commander.decide(row(submission_state=submission))
    assert outcome == commander.READ_ONLY


def test_missing_attribute_waits_for_a_human():
    outcome, _ = commander.decide(row(last_error=(
        'preflight_exception: required_attributes_missing; 平台必填类目属性缺失：尺寸；'
        '需真实资料补齐后续办。; missing_fields=["尺寸"]')))
    assert outcome == commander.WAIT_FACTS


def test_missing_fields_are_extracted_for_the_checklist():
    fields = commander._missing_fields(
        'x; missing_fields=["材质", "适用年龄"]')
    assert fields == ['材质', '适用年龄']


def test_rebaseline_is_not_silently_signed_off():
    # The proof file declares past submissions resolved. Generating that itself would be
    # the machine vouching for its own evidence, so it stays a human confirmation.
    outcome, _ = commander.decide(row(last_error='external_work_requires_rebaseline'))
    assert outcome == commander.WAIT_REBASELINE


def test_rejected_product_needs_a_decision():
    outcome, _ = commander.decide(
        row(last_error='preflight_exception: doudian_draft_or_rejected; ...'))
    assert outcome == commander.WAIT_DECISION


def test_unknown_error_holds_rather_than_guesses():
    outcome, _ = commander.decide(row(last_error='something_new'))
    assert outcome == commander.HOLD_ERROR


def test_facts_loader_drops_blanks_and_placeholders(tmp_path):
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'items': [
        {'product_id': '1', 'attributes': {'尺寸': '30cm', '厚度': ''}},
        {'product_id': '2', 'attributes': {'安装方式': '待确认'}},
    ]}, ensure_ascii=False), encoding='utf-8')
    loaded = commander.load_facts(path)
    assert loaded == {'1': {'尺寸': '30cm'}}


class StubBridge:
    def __init__(self):
        self.calls = []

    def command(self, action, args):
        self.calls.append((action, args))
        return {'success': True}


class StubEditor:
    """Minimal editor double: returns queued control descriptions, records writes."""

    def __init__(self, controls):
        self.controls = list(controls)
        self.bridge = StubBridge()
        self.fills = []

    def dom(self, op, manifest, **kwargs):
        if op == 'attribute_control':
            return self.controls.pop(0) if self.controls else {'error': 'attribute_not_found'}
        if op == 'attribute_options':
            return {'ok': True, 'selector': '[data-doudian-option="x"]'}
        return {}

    def command(self, action, args):
        return self.bridge.command(action, args)


def test_multi_select_is_refused_not_attempted():
    editor = StubEditor([{'kind': 'multi', 'name': '材质', 'current': '请选择'}])
    out = attributes.apply_attributes(editor, {'product_id': '1'},
                                      {'材质': '塑料'})
    assert out[0]['written'] is False
    assert '多选' in out[0]['reason']
    assert editor.bridge.calls == []          # nothing was clicked


def test_placeholder_value_is_skipped():
    editor = StubEditor([])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '待确认'})
    assert out[0]['written'] is False
    assert editor.bridge.calls == []


def test_existing_different_value_is_not_overwritten():
    editor = StubEditor([{'kind': 'text', 'name': '尺寸', 'current': '20cm', 'marked': 'x'}])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is False
    assert '不覆盖' in out[0]['reason']
    assert editor.bridge.calls == []


def test_text_write_reads_back_and_confirms():
    editor = StubEditor([
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
        {'kind': 'text', 'name': '尺寸', 'current': '30cm', 'marked': '[data-x]'},
    ])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is True
    assert out[0]['readback'] == '30cm'


def test_text_write_that_does_not_stick_is_reported():
    # The readback is the authority, not the click returning successfully.
    editor = StubEditor([
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
    ])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is False
    assert '读回值' in out[0]['reason']
