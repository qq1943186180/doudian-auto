"""Title rule tests.

The bounds are pinned to the published platform rules, not to whatever the code
happened to use: 8-30 汉字 == 16-60 platform units. A previous bound of 15 accepted
7.5-character titles that the platform then rejected on submit.
"""

import json
from pathlib import Path

import pytest

from doudian_auto.jobs import read_json, write_json

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


# --- title apply ------------------------------------------------------------
# The revision workflow always replaces images, so a listing needing only a title
# change had no supported path. `title apply` fills that gap; these tests pin the
# safe half (validation and dry-run) without touching a browser.

def test_apply_dry_run_reports_but_does_not_connect(tmp_path, monkeypatch, capsys):
    from doudian_auto import bridge
    monkeypatch.setattr(bridge.Bridge, 'require_ready',
                        lambda self: (_ for _ in ()).throw(AssertionError('browser touched')))
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'apply', '--url', '3848316916011762046',
                 '--shop', '销霁百货', '--title', CJK * 12]) == 0
    payload = json.loads(capsys.readouterr().out)['data']
    assert payload['dry_run'] is True
    assert payload['writes'] == ['标题']


def test_apply_refuses_a_short_title_before_any_write(capsys):
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'apply', '--url', '3848316916011762046',
                 '--shop', '销霁百货', '--title', CJK * 5, '--apply']) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['error']['code'] == 'invalid_title'


def test_apply_rejects_an_invalid_product_reference(capsys):
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'apply', '--url', 'https://evil.example/x',
                 '--shop', '销霁百货', '--title', CJK * 12, '--apply']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'invalid_product'


def test_a_spec_value_repeated_in_the_title_still_counts_when_facts_list_others():
    # Regression: the excuse used to be granted per fact, so a title saying "2件套2件套"
    # escaped the check whenever the facts also listed 3件套.
    facts = TitleFacts({'confirmed': {'specs': {'件数': ['2件套', '3件套']}}})
    report = diagnose_title('折叠扫把簸箕2件套2件套家用扫地刮水器不锈钢杆', facts)
    assert any('重复' in w for w in report['warnings'])


# --- title apply: the writing half ------------------------------------------
# The dry-run half proves nothing about publishing. These drive the real command with
# a fake page so the publish branch, the gates before it and the recovery state all
# have coverage without touching a listing.

PID = '3848316916011762046'
NEW_TITLE = '磁吸折叠扫把簸箕免粘发家用扫地刮水器不锈钢2件套3件套'


def _protected():
    return [
        {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
         'inputs': [], 'selections': ['无品牌'], 'static_fields': [], 'images': []},
        {'section': 'goodsEditScrollContainer-价格库存', 'observation': 'ready',
         'inputs': [], 'selections': ['规格'], 'static_fields': [], 'images': [],
         'price': '20.88', 'checked': True, 'shipping': '48h'},
        {'section': 'goodsEditScrollContainer-服务与履约', 'observation': 'ready',
         'inputs': [], 'selections': ['非偏远'], 'static_fields': [], 'images': []},
    ]


class FakeBridge:
    def __init__(self, endpoint):
        self.session = ''
        self.ready = 0

    def require_ready(self):
        self.ready += 1


class FakeTitleEditor:
    """A page that behaves: fill changes the title, check returns a snapshot, publish once."""

    def __init__(self, bridge, log, page=None, result=None, fail=None):
        self.bridge = bridge
        self.log = log
        self.page = page or {'product_id': PID, 'shop_confirmed': True, 'title': '原有标题',
                              'mains': ['https://cdn/a.jpg'], 'details': ['https://cdn/d.jpg'],
                              'detail_status': 'ready', 'protected': _protected()}
        self.result = result or {'state': 'accepted', 'success': True}
        self.fail = fail
        self.publishes = 0

    def open(self, manifest, fresh=False):
        self.log['opens'] = self.log.get('opens', 0) + 1
        return self.snapshot()

    def read(self, manifest):
        return self.snapshot()

    def fill_title(self, manifest):
        self.page['title'] = manifest['title']

    def check(self, manifest):
        if self.fail == 'validation':
            from doudian_auto.errors import WaitingHuman
            raise WaitingHuman('platform_validation', '平台填写检查发现问题')
        if self.fail == 'commercial':
            self.page['protected'][1]['price'] = '1.00'
        return self.snapshot()

    def publish(self, manifest):
        self.publishes += 1
        self.log['publishes'] = self.publishes
        if self.fail == 'submit_transport':
            raise DoudianError('bridge_transport', 'unknown submit')
        return self.result

    def screenshot(self, path):
        Path(path).write_bytes(b'fixture')

    def snapshot(self):
        return json.loads(json.dumps(self.page))


@pytest.fixture
def apply_run(tmp_path, monkeypatch):
    """Patch the CLI to use a fake page and a temporary data root; return the driver."""
    import doudian_auto.cli as cli
    monkeypatch.setattr(cli, 'DATA_ROOT', tmp_path)
    log = {}
    holder = {}

    def editor_factory(bridge):
        editor = FakeTitleEditor(bridge, log, holder.get('page'), holder.get('result'),
                                 holder.get('fail'))
        holder['editor'] = editor
        return editor

    monkeypatch.setattr(cli, 'Bridge', FakeBridge)
    monkeypatch.setattr(cli, 'Editor', editor_factory)
    facts = tmp_path / 'facts.json'
    facts.write_text(json.dumps({'product_id': PID, 'confirmed': {'material': ['不锈钢']}}),
                     encoding='utf-8')

    def run(extra=None, title=NEW_TITLE, url=PID, with_facts=True):
        from doudian_auto.cli import main
        argv = ['--json', 'title', 'apply', '--url', url, '--shop', '销霁百货',
                '--title', title] + (['--facts', str(facts)] if with_facts else [])
        argv += ['--apply'] if extra is None else extra
        return main(argv)

    holder['run'] = run
    holder['log'] = log
    holder['jobs'] = tmp_path / 'jobs'
    yield holder


def _job_dirs(root):
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def test_apply_publishes_once_and_records_the_change(apply_run, capsys):
    assert apply_run['run']() == 0
    data = json.loads(capsys.readouterr().out)['data']
    assert data['stage'] == 'submitted'
    assert apply_run['log']['publishes'] == 1
    assert apply_run['log']['opens'] >= 1  # open() navigates; read() alone would not
    job = Path(data['job_dir'])
    assert job.name.startswith('title-' + PID)
    assert (job / 'before.json').exists() and (job / 'checked.json').exists()
    assert (job / 'facts.json').exists()  # the input facts are kept, not just the report
    assert read_json(job / 'title_record.json')['before_title'] == '原有标题'
    assert read_json(job / 'state.json')['submission_status'] == 'accepted'


def test_apply_leaves_images_unverified_when_the_detail_source_never_renders(apply_run, capsys):
    apply_run['page'] = {'product_id': PID, 'shop_confirmed': True, 'title': '原有标题',
                         'mains': [], 'details': [], 'detail_status': 'pending',
                         'protected': _protected()}
    assert apply_run['run']() == 0
    data = json.loads(capsys.readouterr().out)['data']
    assert data['image_scope'] == 'not_verified'
    assert '不声称图片未变' in data['image_scope_note']


def test_apply_stops_when_the_platform_check_rejects_the_title(apply_run, capsys):
    apply_run['fail'] = 'validation'
    assert apply_run['run']() == 3  # waiting_human: a human must look at the page
    assert 'publishes' not in apply_run['log']
    job = _single_job(apply_run['jobs'])
    state = read_json(job / 'state.json')
    assert state['stage'] == 'editing'  # the page already carries the typed title
    assert state['last_error'] == 'platform_validation'


def test_apply_stops_when_protected_fields_move_after_check(apply_run, capsys):
    apply_run['fail'] = 'commercial'
    assert apply_run['run']() == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'commercial_changed'
    assert 'publishes' not in apply_run['log']
    assert read_json(_single_job(apply_run['jobs']) / 'state.json')['stage'] == 'editing'


def _single_job(root):
    dirs = [p for p in root.iterdir() if (p / 'state.json').exists()]
    assert len(dirs) == 1
    return dirs[0]


def _publish_result_cases():
    return [
        ({'state': 'accepted'}, 'submitted', 'accepted'),
        ({'state': 'rejected', 'rejection_reasons': ['类目不符']}, 'rejected', 'accepted'),
        ({'state': 'validation_failed', 'errors': ['必填项缺失']}, 'prepared', 'not_submitted'),
        ({'state': 'unknown'}, 'submitting', 'unknown'),
    ]


@pytest.mark.parametrize('result,stage,submission', _publish_result_cases())
def test_apply_records_every_publish_outcome(result, stage, submission, apply_run, capsys):
    apply_run['result'] = result
    code = apply_run['run']()
    job = _single_job(apply_run['jobs'])
    state = read_json(job / 'state.json')
    assert state['stage'] == stage
    assert state['submission_status'] == submission
    if stage == 'submitted':
        assert code == 0
    else:
        # A rejection, a validation failure and an unknown result must never look like
        # a successful submit to the caller.
        assert code != 0
        assert 'publishes' in apply_run['log']


def test_apply_never_republishes_when_the_transport_breaks(apply_run, capsys):
    apply_run['fail'] = 'submit_transport'
    assert apply_run['run']() == 1
    state = read_json(_single_job(apply_run['jobs']) / 'state.json')
    # The submitting state was persisted before the click, so a break leaves a job that
    # must be resolved by verify instead of by publishing again.
    assert state['stage'] == 'submitting'
    assert state['submission_status'] == 'unknown'


def test_apply_does_nothing_when_the_title_is_already_current(apply_run, capsys):
    apply_run['page'] = {'product_id': PID, 'shop_confirmed': True, 'title': NEW_TITLE,
                         'mains': [], 'details': [], 'detail_status': 'ready',
                         'protected': _protected()}
    assert apply_run['run']() == 0
    data = json.loads(capsys.readouterr().out)['data']
    assert data['stage'] == 'noop'
    assert 'publishes' not in apply_run['log']
    state = read_json(_single_job(apply_run['jobs']) / 'state.json')
    assert state['noop_reason'] == 'title_already_current'


def test_apply_is_blocked_by_an_unfinished_sibling(apply_run, capsys):
    sibling = apply_run['jobs'] / 'title-{0}-20261022-120000-abcdef'.format(PID)
    sibling.mkdir(parents=True)
    write_json(sibling / 'manifest.json', {'product_id': PID, 'title': '旧', 'mode': 'title_only'})
    write_json(sibling / 'state.json', {'stage': 'submitting', 'submission_status': 'unknown'})
    assert apply_run['run']() == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'product_job_conflict'
    assert 'publishes' not in apply_run['log']


def test_apply_refuses_facts_that_belong_to_another_product(apply_run, capsys):
    facts = apply_run['jobs'].parent / 'other_facts.json'
    facts.write_text(json.dumps({'product_id': '3790019980637110699'}), encoding='utf-8')
    import doudian_auto.cli as cli
    from doudian_auto.cli import main
    assert main(['--json', 'title', 'apply', '--url', PID, '--shop', '销霁百货',
                 '--title', NEW_TITLE, '--facts', str(facts), '--apply']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'facts_mismatch'


def test_a_second_title_change_gets_its_own_directory(apply_run, capsys):
    from doudian_auto.workflow import Workflow
    assert apply_run['run']() == 0
    first = _single_job(apply_run['jobs'])
    page = apply_run['editor']  # the page that actually received the first change
    # An unverified submit keeps blocking: a newer title change must not overtake a
    # previous one whose result has not been read back yet.
    assert apply_run['run']() == 1
    Workflow(first, page, lock_root=apply_run['jobs'].parent).verify()
    assert read_json(first / 'state.json')['stage'] == 'saved'
    assert apply_run['run']() == 0
    assert len(_job_dirs(apply_run['jobs'])) == 2


def test_a_title_job_can_be_loaded_and_verified(apply_run, capsys):
    from doudian_auto.workflow import Workflow
    assert apply_run['run']() == 0
    job = _single_job(apply_run['jobs'])
    from doudian_auto.jobs import load_job
    manifest = load_job(job)  # used to raise KeyError: 'mains'
    assert manifest['mode'] == 'title_only'
    result = Workflow(job, apply_run['editor'], lock_root=apply_run['jobs'].parent).verify()
    assert result['verified'] is True
    assert read_json(job / 'state.json')['stage'] == 'saved'
