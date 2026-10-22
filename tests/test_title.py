"""Title rule tests.

The bounds are pinned to the published platform rules, not to whatever the code
happened to use: 8-30 汉字 == 16-60 platform units. A previous bound of 15 accepted
7.5-character titles that the platform then rejected on submit.
"""

import json

import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.title import (
    MAX_UNITS,
    MIN_UNITS,
    TitleFacts,
    diagnose_title,
    title_units,
    validate_title,
)

CJK = '波'


def test_bounds_match_the_published_platform_rule():
    # 8 汉字 -> 16 units, 30 汉字 -> 60 units.
    assert MIN_UNITS == 16
    assert MAX_UNITS == 60


def test_counting_treats_cjk_and_fullwidth_as_two_units():
    assert title_units('波') == 2
    assert title_units('a') == 1
    assert title_units('波a') == 3
    assert title_units('') == 0


@pytest.mark.parametrize('text,expected', [
    (CJK * 7, 14),      # just under the floor
    (CJK * 8, 16),      # exactly the floor
    (CJK * 30, 60),     # exactly the ceiling
    (CJK * 31, 62),     # just over the ceiling
])
def test_units_are_computed_on_documented_boundaries(text, expected):
    assert title_units(text) == expected


def test_a_fifteen_unit_title_is_rejected():
    # The regression this fixes: 7 CJK + 1 ASCII = 15 units used to pass.
    text = '吸音棉背胶墙面a'
    assert title_units(text) == 15
    units, errors = validate_title(text)
    assert units == 15
    assert any('少于16' in e for e in errors)


def test_sixteen_units_passes_and_sixty_passes():
    assert validate_title(CJK * 8) == (16, [])
    assert validate_title(CJK * 30) == (60, [])


def test_sixty_two_units_is_rejected():
    _, errors = validate_title(CJK * 31)
    assert any('超过60' in e for e in errors)


def test_empty_and_control_characters_are_deterministic_errors():
    assert validate_title('')[1]
    assert validate_title('   ')[1]
    _, errors = validate_title(CJK * 10 + '\x00')
    assert any('控制字符' in e for e in errors)


def test_surrounding_whitespace_is_reported_not_silently_trimmed():
    # The exact bytes go into the manifest hash, so trimming would produce a job that
    # differs from what the operator typed.
    units, errors = validate_title(' ' + CJK * 10 + ' ')
    assert any('首尾含空白' in e for e in errors)
    assert title_units(' ' + CJK * 10 + ' ') == units


def test_risky_claim_marked_unconfirmed_is_called_out_by_name():
    facts = TitleFacts({'unconfirmed': ['防火']})
    report = diagnose_title('吸音棉防火阻燃墙面自粘背胶室内用隔音', facts)
    assert any('防火' in w and '未经证实' in w for w in report['warnings'])


def test_risky_claim_without_evidence_is_flagged_as_unverifiable():
    report = diagnose_title('吸音棉防火墙面自粘背胶室内用隔音材料')
    assert any('防火' in w and ('无法核实' in w or '需资质' in w) for w in report['warnings'])


@pytest.mark.parametrize('text', [
    '吸音棉自粘背胶室内墙面9.9元包邮隔音材料',
    '吸音棉自粘背胶室内墙面￥59隔音材料',
    '吸音棉自粘背胶室内墙面特价隔音材料',
])
def test_price_in_title_is_flagged(text):
    report = diagnose_title(text)
    assert any('价格' in w for w in report['warnings'])


def test_generic_basket_words_are_flagged():
    report = diagnose_title('吸音棉自粘背胶室内墙面隔音材料百货套装好物')
    joined = ' '.join(report['warnings'])
    for word in ('百货', '套装', '好物'):
        assert word in joined


def test_repeated_phrase_is_flagged():
    report = diagnose_title('波浪吸音棉鸡蛋棉吸音棉墙面吸音棉自粘背胶室内用')
    assert any('重复' in w for w in report['warnings'])


def test_numeric_spec_without_confirmed_facts_is_flagged():
    # An empty confirmed-spec set must not be read as "nothing to check": a made-up
    # thickness is exactly the case that needs reporting.
    facts = TitleFacts({'confirmed': {'specs': {}}})
    report = diagnose_title('吸音棉自粘背胶室内墙面5cm厚隔音材料', facts)
    assert any('5cm' in w for w in report['warnings'])


def test_numeric_spec_backed_by_confirmed_facts_is_not_flagged():
    facts = TitleFacts({'confirmed': {'specs': {'厚度': ['5cm']}}})
    report = diagnose_title('吸音棉自粘背胶室内墙面5cm厚隔音材料', facts)
    assert not any('数值' in w for w in report['warnings'])


def test_confirmed_but_unused_facts_are_reported():
    facts = TitleFacts({'confirmed': {'material': ['聚氨酯']}})
    report = diagnose_title('吸音棉自粘背胶室内墙面隔音材料', facts)
    assert any('未使用' in w and '聚氨酯' in w for w in report['warnings'])


def test_diagnose_never_claims_platform_compliance():
    report = diagnose_title('波浪吸音棉鸡蛋棉自粘背胶室内录音棚墙面用多厚度可选')
    assert report['ok'] is True
    assert '不代表平台通过' in report['coverage']
    assert '本地计数' in report['counting_note']


def test_diagnose_reports_deterministic_errors_and_still_returns_a_report():
    report = diagnose_title(CJK * 5)
    assert report['ok'] is False
    assert report['errors']
    # Warnings are computed too; the caller decides what to do with them.
    assert isinstance(report['warnings'], list)


def test_facts_ignore_the_no_brand_placeholder_as_a_title_keyword():
    # "无品牌" is a platform dropdown value, not a selling point to type into a title.
    facts = TitleFacts({'confirmed': {'brand': '无品牌'}})
    assert '无品牌' not in facts.phrases


def test_facts_accept_scalars_and_lists():
    facts = TitleFacts({'confirmed': {'material': '聚氨酯', 'scene': ['室内'], 'specs': {'厚度': '5cm'}}})
    assert facts.material == ['聚氨酯']
    assert facts.scene == ['室内']
    assert facts.spec_values == ['5cm']


def test_facts_tolerate_an_empty_payload():
    facts = TitleFacts()
    assert facts.phrases == []
    assert facts.spec_values == []
    report = diagnose_title('吸音棉自粘背胶室内墙面6mm厚隔音材料', facts)
    assert any('6mm' in w for w in report['warnings'])


def test_cli_check_passes_with_json_output(capsys):
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'check', '--title', CJK * 20]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is True
    assert payload['data']['units'] == 40
    assert payload['data']['limits'] == {'min': 16, 'max': 60}


def test_cli_check_fails_and_exits_non_zero_on_a_short_title(capsys):
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'check', '--title', CJK * 5]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is False
    assert payload['error']['code'] == 'invalid_title'


def test_cli_check_does_not_need_a_browser(tmp_path, monkeypatch, capsys):
    # title work is offline; a dead bridge must not matter.
    from doudian_auto import bridge
    monkeypatch.setattr(bridge.Bridge, 'require_ready',
                        lambda self: (_ for _ in ()).throw(AssertionError('bridge used')))
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'check', '--title', CJK * 20]) == 0


def test_cli_diagnose_reads_a_facts_file(tmp_path, capsys):
    facts = tmp_path / 'facts.json'
    facts.write_text(json.dumps({'confirmed': {'material': ['聚氨酯']},
                                 'unconfirmed': ['防火']}), encoding='utf-8')
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'diagnose', '--title', '吸音棉防火墙面自粘背胶室内用隔音材料',
                 '--facts', str(facts)]) == 0
    payload = json.loads(capsys.readouterr().out)['data']
    assert any('未经证实' in w for w in payload['warnings'])


def test_prepare_rejects_a_title_below_the_platform_floor(tmp_path):
    from doudian_auto.jobs import prepare
    from PIL import Image
    assets = tmp_path / 'assets'
    assets.mkdir()
    for i in range(1, 6):
        Image.new('RGB', (640, 640), (i * 20, 90, 140)).save(assets / 'main_0{0}.jpg'.format(i))
    Image.new('RGB', (800, 1200), (10, 20, 30)).save(assets / 'detail_01.jpg')
    with pytest.raises(DoudianError) as exc:
        prepare(assets, CJK * 7, 'https://fxg.jinritemai.com/ffa/g/create?product_id=3784643089604411407',
                '样板店', tmp_path / 'jobs')
    assert exc.value.code == 'invalid_title'
    assert '少于16' in str(exc.value)


def test_vague_superlatives_are_flagged():
    # "神器" is not in the learning-centre wording but sits in the same class as the
    # named examples; it showed up in a real listing with no evidence behind it.
    report = diagnose_title('折叠扫把簸箕免粘发家用扫地神器不锈钢两件套三件套')
    assert any('神器' in w for w in report['warnings'])


def test_listing_two_spec_variants_is_not_flagged_as_repetition():
    # "2件套3件套" repeats the bigram "件套" only because both variants are listed.
    facts = TitleFacts({'confirmed': {'specs': {'件数': ['2件套', '3件套']}}})
    report = diagnose_title('磁吸折叠扫把簸箕免粘发家用扫地刮水器不锈钢2件套3件套', facts)
    assert not any('重复' in w for w in report['warnings'])


def test_a_phrase_repeated_inside_one_spec_value_still_counts():
    facts = TitleFacts({'confirmed': {'specs': {'件数': ['2件套']}}})
    report = diagnose_title('折叠扫把簸箕2件套2件套家用扫地刮水器不锈钢杆', facts)
    assert any('重复' in w for w in report['warnings'])
