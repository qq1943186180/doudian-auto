"""Mapping supplier spec onto Douyin attributes.

The rule under test is that only what the supplier page states outright is used. A value
that would have to be inferred, or borrowed from a similar product, must be absent from
the result rather than guessed.
"""

from doudian_auto.source_facts import (facts_for_douyin, needs_human,
                                       unsupported_but_asked)


def spec(**pairs):
    return {'pairs': pairs, 'location': '', 'supplier': ''}


def test_stated_values_map_to_douyin_names():
    got = facts_for_douyin(spec(**{'是否进口': '否', '货号': '吸盘毛巾架', '材质': 'ABS'}))
    assert got == {'是否进口': '否', '型号': '吸盘毛巾架', '材质': 'ABS'}


def test_material_name_is_kept_but_material_type_is_not_invented():
    # The page says ABS. It does not say which multi-select bucket the platform wants.
    got = facts_for_douyin(spec(**{'材质': 'ABS'}))
    assert got['材质'] == 'ABS'
    assert '材质类型' not in got


def test_a_placeholder_value_is_not_used():
    # "咨询客服" is the supplier declining to state a value, not a value.
    got = facts_for_douyin(spec(**{'箱装数量': '咨询客服', '是否进口': '否'}))
    assert got == {'是否进口': '否'}


def test_origin_needs_a_place_not_just_a_company():
    no_place = {'pairs': {}, 'location': '', 'supplier': '义乌市寄舟贸易有限公司'}
    assert '产地' not in facts_for_douyin(no_place)

    with_place = {'pairs': {}, 'location': '浙江金华', 'supplier': '义乌市寄舟贸易有限公司'}
    assert facts_for_douyin(with_place)['产地'] == '浙江金华'


def test_unsupported_lists_what_the_page_cannot_answer():
    missing = unsupported_but_asked(spec(**{'是否进口': '否', '材质': 'ABS'}))
    assert '是否可接触食品' in missing
    assert '材质类型' in missing
    assert '生产企业地址' in missing


def test_attributes_the_source_cannot_answer_are_named_as_such():
    # Reading the supplier page again cannot answer these; the user has to supply them.
    askable, blocked = needs_human(['安装方式', '尺寸', '是否进口', '材质'])
    assert set(blocked) == {'安装方式', '尺寸'}
    assert set(askable) == {'是否进口', '材质'}
    assert '1688' in blocked['尺寸']


def test_an_unknown_attribute_is_treated_as_askable():
    askable, blocked = needs_human(['商品类型'])
    assert '商品类型' in askable and not blocked


def test_attributes_the_source_cannot_answer_are_named_as_such():
    # Reading the supplier page again cannot answer these; the user has to supply them.
    askable, blocked = needs_human(['安装方式', '尺寸', '是否进口', '材质'])
    assert set(blocked) == {'安装方式', '尺寸'}
    assert set(askable) == {'是否进口', '材质'}
    assert '1688' in blocked['尺寸']


def test_an_unknown_attribute_is_treated_as_askable():
    askable, blocked = needs_human(['商品类型'])
    assert '商品类型' in askable and not blocked
