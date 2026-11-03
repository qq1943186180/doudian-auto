from copy import deepcopy

import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.workflow import compare_protected
from test_preflight import _snapshot


def pair():
    before = _snapshot({'product_id': '3850071689249554608'})
    options = [{'type': 'checkbox', 'name': '', 'value': name, 'checked': False, 'disabled': False}
               for name in ('靴筒围(cm)', '鞋底厚(cm)', '靴筒高(cm)', '鞋跟高(cm)')]
    price = {'type': 'text', 'name': 'price', 'value': '10.00', 'checked': None, 'disabled': False}
    before['protected'][1]['inputs'] = [price, *deepcopy(options)]
    before['protected'].append({'section': 'goodsEditScrollContainer-尺码表', 'observation': 'ready',
                                'inputs': deepcopy(options), 'selections': [], 'static_fields': [], 'images': []})
    after = deepcopy(before)
    after['protected'][1]['inputs'][1:] = list(reversed(after['protected'][1]['inputs'][1:]))
    after['protected'][-1]['inputs'].reverse()
    return before, after


def test_only_measured_inactive_options_can_reorder_without_mutating_evidence():
    before, after = pair()
    originals = deepcopy((before, after))
    compare_protected(before, after)
    assert (before, after) == originals


@pytest.mark.parametrize('change', ['selected', 'disabled', 'missing', 'duplicate', 'extra_field',
                                   'price', 'interleaved', 'other_section', 'no_full_sku', 'changed_sku'])
def test_size_option_order_never_waives_real_changes_or_missing_evidence(change):
    before, after = pair()
    inputs = after['protected'][1]['inputs']
    if change == 'selected':
        inputs[1]['checked'] = True
    elif change == 'disabled':
        inputs[1]['disabled'] = True
    elif change == 'missing':
        inputs.pop()
    elif change == 'duplicate':
        inputs[1]['value'] = inputs[2]['value']
    elif change == 'extra_field':
        inputs[1]['unobserved_property'] = 'new'
    elif change == 'price':
        inputs[0]['value'] = '99.00'
    elif change == 'interleaved':
        inputs.insert(2, inputs.pop(0))
    elif change == 'other_section':
        before['protected'][-1]['section'] = after['protected'][-1]['section'] = 'other_section'
    elif change == 'no_full_sku':
        before.pop('sku_evidence');after.pop('sku_evidence')
    elif change == 'changed_sku':
        after['sku_evidence']['rows'][0]['price'] = '99'
    with pytest.raises(DoudianError):
        compare_protected(before, after)
