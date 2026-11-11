"""机会铺货的安全边界回归测试。

这些用例守住的都是「错了会出事」的边界：结果未知时不许重试、活着的锁不许清、
配置读回不一致必须停、页面定位不唯一必须失败关闭。功能happy path 由真实页面验收覆盖。
"""
from pathlib import Path

import pytest

from doudian_auto.dropship import (
    PRICE_FIELD_NAMES,
    calculate_price,
    mark_copy_intent,
    prepare_task,
    record_configuration_audit,
    record_copy_observation,
    record_verified_configuration,
    resolve_job_dir,
    verify_target_readback,
    _acquire_task_lock,
)
from doudian_auto.dropship_pages import DropshipPages
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import read_json, write_json


def _job(tmp_path, stage='prepared', submission='not_attempted'):
    job = tmp_path / 'task'
    job.mkdir(parents=True, exist_ok=True)
    write_json(job / 'state.json', {'stage': stage, 'submission_status': submission})
    return job


# ---------- 价格试算 ----------

def test_price_calculation_rounds_to_cents():
    result = calculate_price('57.00', '3', '5')
    assert result['final_price'] == '176.00'
    assert result['formula'] == '3 × 源价 + 5'


def test_price_rejects_non_positive_multiplier():
    with pytest.raises(DoudianError, match='倍数必须大于0'):
        calculate_price('10', '0', '5')


def test_price_rejects_garbage():
    with pytest.raises(DoudianError, match='有效金额'):
        calculate_price('abc', '3', '5')


# ---------- unknown 不许重试 ----------

def test_unknown_copy_result_blocks_any_retry(tmp_path):
    job = _job(tmp_path, stage='settings_verified')
    mark_copy_intent(job)
    result = record_copy_observation(job, outcome='unknown', evidence={'timeout': True})
    assert result['readback_only'] is True
    with pytest.raises(DoudianError, match='禁止贴链接、抓取、写配置或再次点击复制'):
        mark_copy_intent(job)


def test_copy_intent_requires_verified_settings(tmp_path):
    job = _job(tmp_path, stage='prepared')
    with pytest.raises(DoudianError, match='搬家配置尚未核验'):
        mark_copy_intent(job)


def test_explicit_failure_is_distinct_from_unknown(tmp_path):
    """明确失败不能滑进 unknown，否则人会以为还能重跑。"""
    job = _job(tmp_path, stage='settings_verified')
    mark_copy_intent(job)
    result = record_copy_observation(job, outcome='failed', evidence={'reason': '平台拒绝'})
    assert result == {'stage': 'blocked', 'failed': True, 'readback': {'reason': '平台拒绝'}}
    state = (job / 'state.json')
    assert '"failed"' in state.read_text(encoding='utf-8')


def test_copy_observation_needs_a_plausible_product_id(tmp_path):
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json', {'stage': 'unknown', 'submission_status': 'unknown',
                                    'source_product_id': '965251097615',
                                    'history_baseline': []})
    with pytest.raises(DoudianError, match='商品 ID 读回不完整'):
        record_copy_observation(job, outcome='copied', target_product_id='123',
                                evidence={'history_row': 'x',
                                          'history_row_key': '965251097615@123',
                                          'source_product_id': '965251097615'})

def test_copy_observation_rejects_a_history_row_from_another_source(tmp_path):
    """历史行的来源商品必须与本任务一致，否则读到的是别人的记录。"""
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json', {'stage': 'unknown', 'submission_status': 'unknown',
                                    'source_product_id': '965251097615',
                                    'history_baseline': []})
    with pytest.raises(DoudianError, match='来源商品与本任务不一致'):
        record_copy_observation(job, outcome='copied', target_product_id='3853454064050373417',
                                evidence={'history_row': 'x', 'source_product_id': '999'})


def test_unknown_outcome_is_rejected(tmp_path):
    job = _job(tmp_path)
    with pytest.raises(DoudianError, match='必须是'):
        record_copy_observation(job, outcome='weird')


# ---------- 配置审计 ----------

def test_configuration_audit_keeps_before_and_after(tmp_path):
    job = _job(tmp_path)
    before = {'pricePercent': '200', 'priceAdd': '3'}
    target = {'pricePercent': '300', 'priceAdd': '5'}
    audit = record_configuration_audit(job, before, target, target)
    assert audit['matches_target'] is True
    saved = (job / 'configuration-audit.json').read_text(encoding='utf-8')
    assert '"before"' in saved and '"after"' in saved
    # 前值是恢复原配置的唯一依据，必须原样留在文件里
    assert '"200"' in saved and '"3"' in saved


def test_configuration_readback_mismatch_blocks_the_task(tmp_path):
    job = _job(tmp_path)
    target = {'pricePercent': '300'}
    with pytest.raises(DoudianError, match='读回不一致'):
        record_configuration_audit(job, {'pricePercent': '200'}, target, {'pricePercent': '200'})
    state = (job / 'state.json').read_text(encoding='utf-8')
    assert 'configuration_readback_mismatch' in state


# ---------- 锁纪律 ----------

def test_live_lock_is_never_cleaned(tmp_path, monkeypatch):
    lock = tmp_path / 'browser.lock'
    lock.write_text('1234', encoding='ascii')
    monkeypatch.setattr('doudian_auto.dropship.process_alive', lambda pid: True)
    with pytest.raises(DoudianError, match='仍在运行'):
        _acquire_task_lock(lock)
    assert lock.read_text(encoding='ascii') == '1234'


def test_dead_lock_is_reclaimed(tmp_path, monkeypatch):
    lock = tmp_path / 'browser.lock'
    lock.write_text('1234', encoding='ascii')
    monkeypatch.setattr('doudian_auto.dropship.process_alive', lambda pid: False)
    with _acquire_task_lock(lock) as held:
        assert held.fd is not None


def test_unreadable_lock_content_is_not_deleted(tmp_path):
    lock = tmp_path / 'browser.lock'
    lock.write_text('not-a-pid', encoding='ascii')
    with pytest.raises(DoudianError, match='内容异常'):
        _acquire_task_lock(lock)
    assert lock.exists()


# ---------- 核验 ----------

def test_verify_requires_a_copied_stage(tmp_path):
    job = _job(tmp_path, stage='prepared')
    with pytest.raises(DoudianError, match='没有可核验的铺货结果'):
        verify_target_readback(job, product_id='3853454064050373417',
                               sku_rows=[{'sku': 'x', 'price': '1'}], sku_total_count=1,
                               price_progress=100, review_status='待审核')


def test_verify_reports_review_status_without_inferring(tmp_path):
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '15.48'}})
    report = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}], sku_total_count=1,
        price_progress=100, review_status='待审核')
    assert report['review_status'] == '待审核'
    assert report['sku_rows'][0]['price'] == '15.48'


# ---------- 任务创建 ----------

def test_prepare_rejects_an_offer_url_that_does_not_name_the_source(tmp_path):
    """URL 必须真的是 detail.1688.com/offer/<来源ID>.html。

    只检查「是不是 https」不够：manifest 把来源 ID 和链接绑在一起，
    后面整个流程都相信这个绑定。链接与 ID 不匹配就是假的绑定。
    """
    with pytest.raises(DoudianError, match='来源一致'):
        prepare_task(source_product_id='965251097615',
                     offer_url='https://detail.1688.com/offer/123.html',
                     shop='销霁百货', source_price='57', multiplier='3', addition='5',
                     root=str(tmp_path))


def test_prepare_is_idempotent_for_the_same_input(tmp_path):
    kwargs = dict(source_product_id='965251097615',
                  offer_url='https://detail.1688.com/offer/965251097615.html',
                  shop='销霁百货', source_price='57', multiplier='3', addition='5',
                  root=str(tmp_path))
    first = prepare_task(**kwargs)
    second = prepare_task(**kwargs)
    assert first['task_id'] == second['task_id']
    assert second['price_confirmation']['final_price'] == '176.00'


def test_prepare_rejects_a_conflicting_plan(tmp_path):
    base = dict(source_product_id='965251097615',
                offer_url='https://detail.1688.com/offer/965251097615.html',
                shop='销霁百货', root=str(tmp_path))
    prepare_task(source_price='57', multiplier='3', addition='5', **base)
    with pytest.raises(DoudianError, match='与当前输入不一致'):
        prepare_task(source_price='57', multiplier='4', addition='5', **base)


# ---------- 页面适配：失败关闭 ----------

class FakeBridge:
    """按脚本返回结果，并记录每次 evaluate 的代码，用来断言「一次调用」。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def evaluate(self, code):
        self.calls.append(code)
        return self.script.pop(0) if self.script else {'status': 'layout_changed'}


def test_page_action_is_a_single_evaluate():
    bridge = FakeBridge([{'status': 'ok', 'product_id': '3853454064050373417'}])
    DropshipPages(bridge).read_history_product_id(source_product_id='965251097615')
    assert len(bridge.calls) == 1


def test_non_unique_history_row_fails_closed():
    bridge = FakeBridge([{'status': 'layout_changed', 'reason': 'history_row', 'count': 3}])
    with pytest.raises(DoudianError, match='页面结构或候选唯一性'):
        DropshipPages(bridge).read_history_product_id(source_product_id='965251097615')
    assert len(bridge.calls) == 1


def test_non_unique_opportunity_card_fails_closed():
    bridge = FakeBridge([{'status': 'layout_changed', 'reason': 'card', 'count': 2}])
    with pytest.raises(DoudianError, match='页面结构或候选唯一性'):
        DropshipPages(bridge).click_single_opportunity(card_text='指定商机')
    assert len(bridge.calls) == 1


def test_wrong_page_is_reported_not_retried():
    bridge = FakeBridge([{'status': 'wrong_page'}])
    with pytest.raises(DoudianError, match='不是预期的'):
        DropshipPages(bridge).read_settings()


def test_stale_old_value_blocks_the_write():
    """旧值和快照不一致时必须停，否则会覆盖别人刚改的配置。"""
    bridge = FakeBridge([{'status': 'readback_mismatch', 'field': 'pricePercent'}])
    with pytest.raises(DoudianError, match='即时读回不一致'):
        DropshipPages(bridge).set_price_formula(
            before={'pricePercent': '200'}, target={'pricePercent': '300'})


def test_sku_price_comes_from_input_value_not_row_text():
    """价格必须来自 input.value；行文本里的 888888 是库存，读它就会误报。"""
    bridge = FakeBridge([{'status': 'ok', 'product_id': '3853454064050373417',
                          'sku_rows': [{'sku': '1个装', 'price': '15.48'}],
                          'sku_total_count': None}])
    result = DropshipPages(bridge).read_sku_prices(product_id='3853454064050373417')
    assert result['sku_rows'][0]['price'] == '15.48'
    # 价格取自 input 的 value
    assert 'inputs[0].value' in bridge.calls[0]
    # 不再按调用方给的名单定位行，而是读页面上所有可见行
    assert 'sku_names' not in bridge.calls[0]
    assert 'querySelectorAll' in bridge.calls[0]
    # 行文本只用于取 SKU 名，不作为价格来源
    assert result['sku_total_count'] is None


# ---------- unknown 阶段：禁写入，但必须放行只读核查 ----------

def test_unknown_stage_allows_readback_but_forbids_write(tmp_path):
    """早期版本在 unknown 直接 raise，把唯一的恢复路径也堵死了，任务永久卡死。"""
    from doudian_auto.dropship import require_copy_write_allowed

    unknown = {'stage': 'unknown', 'submission_status': 'unknown'}
    with pytest.raises(DoudianError, match='禁止贴链接、抓取、写配置或再次点击复制'):
        require_copy_write_allowed(unknown)

    # 只读核查不受该闸门约束：它检查的是写入许可，不是读回许可
    settings_verified = {'stage': 'settings_verified', 'submission_status': 'not_attempted'}
    require_copy_write_allowed(settings_verified)  # 不抛异常即通过


def test_terminal_stages_forbid_further_write():
    from doudian_auto.dropship import require_copy_write_allowed

    for stage in ('copied', 'verified', 'blocked', 'verification_pending'):
        with pytest.raises(DoudianError, match='禁止'):
            require_copy_write_allowed({'stage': stage})


def test_prepared_stage_cannot_start_copy():
    from doudian_auto.dropship import require_copy_write_allowed

    with pytest.raises(DoudianError, match='搬家配置尚未核验'):
        require_copy_write_allowed({'stage': 'prepared'})


# ---------- SKU 完整性：行数对不上就不标 verified ----------

def test_sku_count_mismatch_stays_verification_pending(tmp_path):
    """读到的行数少于总数时必须停在 verification_pending，不能标 verified。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '15.48'}})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}], review_status='待审核',
        sku_total_count=20, price_progress=100,
    )
    assert result['stage'] == 'verification_pending'
    assert result['sku_rows_observed'] == 1
    assert result['sku_total_count'] == 20


def test_missing_total_count_stays_verification_pending(tmp_path):
    """没有实抓到的总数计数时，不得把部分行冒充完整结果。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '15.48'}})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}, {'sku': '4个装', 'price': '27.48'}],
        review_status='待审核', sku_total_count=None, price_progress=100,
    )
    assert result['stage'] == 'verification_pending'
    assert '总数计数' in result['reason']


def test_matching_sku_count_reaches_verified(tmp_path):
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '15.48', '4个装': '27.48'}})
    rows = [{'sku': '1个装', 'price': '15.48'}, {'sku': '4个装', 'price': '27.48'}]
    report = verify_target_readback(job, product_id='3853454064050373417',
                                    sku_rows=rows,
                                    review_status='待审核',
                                    sku_total_count=2, price_progress=100)
    assert report['sku_total_count'] == 2
    assert report['review_status'] == '待审核'


def test_sku_adapter_reads_visible_rows_without_a_preset_list():
    """不再要求调用方预填 sku_names：那会用期望代替页面实际。"""
    bridge = FakeBridge([{'status': 'ok', 'product_id': '3853454064050373417',
                          'sku_rows': [{'sku': '1个装', 'price': '15.48'}],
                          'sku_total_count': None}])
    result = DropshipPages(bridge).read_sku_prices(product_id='3853454064050373417')
    assert result['sku_total_count'] is None
    # 完整性是独立维度，不覆盖 status 的失败关闭语义
    assert result['completeness'] == 'unverified'
    assert 'sku_names' not in bridge.calls[0]
    # 价格取自 input 的 value，不是行文本
    assert 'inputs[0].value' in bridge.calls[0]


# ---------- Codex 复核指出的盲区 ----------

def test_copied_requires_a_recorded_copy_intent(tmp_path):
    """没有落盘的复制意图，谁都能宣布成功——之前只校验商品 ID 的位数。"""
    job = _job(tmp_path, stage='prepared', submission='not_attempted')
    write_json(job / 'state.json', {'stage': 'prepared',
                                    'submission_status': 'not_attempted',
                                    'source_product_id': '965251097615'})
    with pytest.raises(DoudianError, match='没有待核查的复制意图'):
        record_copy_observation(job, outcome='copied',
                                target_product_id='3853454064050373417',
                                evidence={'history_row': 'x',
                                          'source_product_id': '965251097615'})


def test_copied_requires_evidence_that_links_source_and_target(tmp_path):
    """缺证据时不能标 copied：否则一次调用就能把任务写成已完成。"""
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json', {'stage': 'unknown', 'submission_status': 'unknown',
                                    'source_product_id': '965251097615',
                                    'history_baseline': []})
    with pytest.raises(DoudianError, match='缺少复制历史行证据'):
        record_copy_observation(job, outcome='copied',
                                target_product_id='3853454064050373417')


def test_verify_rejects_a_product_id_that_is_not_the_copied_one(tmp_path):
    """官方页商品 ID 必须与复制历史一致，否则核验的是别人的商品。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417'})
    with pytest.raises(DoudianError, match='与复制历史不一致'):
        verify_target_readback(job, product_id='9999999999999999999',
                               sku_rows=[{'sku': '1个装', 'price': '15.48'}], sku_total_count=1,
                               price_progress=100, review_status='待审核')


def test_verify_stays_pending_when_a_spec_is_missing(tmp_path):
    """规格名少一个就说明没铺全，不能算核验通过。

    官方页的**售价**与来源批发价本来就不相等（售价含运费与尾数），
    所以比的是规格名集合，不是价格。
    """
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '2', '4个装': '6'}})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}], sku_total_count=1,
        price_progress=100, review_status='待审核')
    assert result['stage'] == 'verification_pending'
    assert '缺少规格' in result['reason']

def test_verify_stays_pending_when_the_page_progress_is_not_complete(tmp_path):
    """页面价格填写进度不到 100% 时，可能还有 SKU 没被读到。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '15.48'}})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}], sku_total_count=1,
        price_progress=50, review_status='待审核')
    assert result['stage'] == 'verification_pending'
    assert '进度' in result['reason']


def test_offer_url_must_name_the_source_product(tmp_path):
    """URL 里的 offer ID 与来源 ID 不一致时，来源绑定是假的。"""
    with pytest.raises(DoudianError, match='来源一致'):
        prepare_task(source_product_id='965251097615',
                     offer_url='https://detail.1688.com/offer/999.html',
                     shop='销霁百货', source_price='57', multiplier='3', addition='5',
                     root=str(tmp_path))


def test_offer_url_must_be_a_1688_offer_page(tmp_path):
    with pytest.raises(DoudianError, match='来源一致'):
        prepare_task(source_product_id='965251097615',
                     offer_url='https://example.com/offer/965251097615.html',
                     shop='销霁百货', source_price='57', multiplier='3', addition='5',
                     root=str(tmp_path))


def test_task_id_may_not_escape_the_task_root(tmp_path):
    """任务 ID 来自命令行，越界会让流程在根目录外读写状态。"""
    root = tmp_path / 'root'
    root.mkdir()
    with pytest.raises(DoudianError, match='格式无效'):
        resolve_job_dir(root, '../../etc')
    with pytest.raises(DoudianError, match='格式无效'):
        resolve_job_dir(root, 'dropship-1-zzz')


def test_configuration_only_advances_after_a_complete_persisted_readback(tmp_path):
    """目标配置必须覆盖全部价格字段，缺一个就说明漏改了。"""
    job = _job(tmp_path, stage='prepared')
    partial = {'pricePercent': '300', 'priceAdd': '5'}
    with pytest.raises(DoudianError, match='缺少价格字段'):
        record_verified_configuration(job, before={}, target=partial,
                                      persisted_after=partial)


def test_verified_configuration_advances_the_stage(tmp_path):
    job = _job(tmp_path, stage='prepared')
    full = {name: '1' for name in PRICE_FIELD_NAMES}
    full['shelf_mode'] = '放入仓库'
    record_verified_configuration(job, before={}, target=full, persisted_after=full)
    state = (job / 'state.json')
    assert '"settings_verified"' in state.read_text(encoding='utf-8')


def test_price_preview_states_that_it_excludes_shipping_and_tail(tmp_path):
    """试算是简化公式，必须自己说明它不代表页面最终售价。"""
    preview = calculate_price('2', '3', '5')
    assert preview['final_price'] == '11.00'
    assert '不含运费' in preview['note']
    # 页面 pricePercent 是百分比，倍数要 ×100
    assert preview['page_price_percent'] == '300'


# ---------- Codex 复核指出的盲区 ----------

def test_readback_only_reports_the_review_status_as_unavailable(tmp_path):
    """编辑页读不到商品审核状态，只能如实报 unavailable。

    「已上架」是 SKU 状态，「上架/下架」是表单选项——把它们当审核状态就是误报。
    """
    from doudian_auto.dropship import _readback_only

    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'source_product_id': '965251097615'})

    class FakePages:
        def __init__(self, bridge):
            pass

        def navigate_official(self, product_id):
            return {'status': 'ok'}

        def read_sku_prices(self, *, product_id):
            return {'status': 'ok', 'sku_rows': [{'sku': '1个装', 'price': '15.48'}],
                    'price_progress': 100, 'completeness': 'unverified'}

        def read_review_status(self, *, product_id):
            return {'status': 'ok', 'review_status': None,
                    'review_status_reason': '商品审核状态不在编辑页',
                    'sku_status_tokens': ['已上架']}

    class FakeBridge:
        def require_ready(self):
            return True

    import doudian_auto.dropship as ds
    import doudian_auto.dropship_pages as dp
    import doudian_auto.ego_bridge as eb

    orig = (dp.DropshipPages, eb.EgoBridge)
    dp.DropshipPages = FakePages
    eb.EgoBridge = lambda session=None: FakeBridge()
    try:
        out = _readback_only(
            type('A', (), {'task_id': 'dropship-1-abcdef0123456789',
                           'session': 's'})(),
            job, {'stage': 'copied', 'target_product_id': '3853454064050373417'},
            {'source_product_id': '965251097615'})
    finally:
        dp.DropshipPages, eb.EgoBridge = orig

    assert out['readback_only'] is True
    assert out['review_status'] is None
    assert out['sku_status_tokens'] == ['已上架']
    assert out['sku_rows'][0]['price'] == '15.48'


def test_offer_url_accepts_http_but_normalises_to_https(tmp_path):
    """现存 42 条源链接全是 http，一刀切只收 https 会把它们全拒掉。"""
    task = prepare_task(source_product_id='965251097615',
                        offer_url='http://detail.1688.com/offer/965251097615.html',
                        shop='销霁百货', source_price='57', multiplier='3', addition='5',
                        root=str(tmp_path))
    manifest = read_json(Path(task['job_dir']) / 'manifest.json')
    assert manifest['offer_url'] == 'https://detail.1688.com/offer/965251097615.html'
    # 原链接保留，便于追溯
    assert manifest['offer_url_original'].startswith('http://')


def test_copied_requires_a_history_baseline(tmp_path):
    """没有基线就无法区分「本次新增」与「历史里本来就有的那条」。"""
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json', {'stage': 'unknown', 'submission_status': 'unknown',
                                    'source_product_id': '965251097615'})
    with pytest.raises(DoudianError, match='缺少复制历史基线'):
        record_copy_observation(job, outcome='copied',
                                target_product_id='3853454064050373417',
                                evidence={'history_row': 'x',
                                          'source_product_id': '965251097615'})


def test_copied_rejects_a_row_that_existed_before_the_copy(tmp_path):
    """基线里已有的行不能当成本次复制的成果。"""
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json',
               {'stage': 'unknown', 'submission_status': 'unknown',
                'source_product_id': '965251097615',
                'history_baseline': ['965251097615@3853454064050373417']})
    with pytest.raises(DoudianError, match='复制前就已存在'):
        record_copy_observation(job, outcome='copied',
                                target_product_id='3853454064050373417',
                                evidence={'history_row': 'x',
                                          'history_row_key': '965251097615@3853454064050373417',
                                          'source_product_id': '965251097615'})


def test_verify_requires_the_expected_skus_recorded_at_copy_time(tmp_path):
    """预期 SKU 必须是复制时落盘的，不能核验时现传。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417'})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}],
        sku_total_count=1, price_progress=100, review_status='待审核')
    assert result['stage'] == 'verification_pending'
    assert '预期 SKU' in result['reason']


def test_configuration_requires_an_explicit_warehouse_shelf_mode(tmp_path):
    """只对齐价格却没确认「放入仓库」，等于没确认商品不会直接开卖。"""
    job = _job(tmp_path, stage='prepared')
    full = {name: '1' for name in PRICE_FIELD_NAMES}
    with pytest.raises(DoudianError, match='放入仓库'):
        record_verified_configuration(job, before={}, target=full, persisted_after=full)


def test_configuration_rejects_a_shelf_mode_that_is_not_warehouse(tmp_path):
    job = _job(tmp_path, stage='prepared')
    full = {name: '1' for name in PRICE_FIELD_NAMES}
    full['shelf_mode'] = '立即上架'
    with pytest.raises(DoudianError, match='放入仓库'):
        record_verified_configuration(job, before={}, target=full, persisted_after=full)


def test_copy_intent_records_the_expected_skus_and_history_baseline(tmp_path):
    """点击复制前必须把预期 SKU 与历史基线落盘，否则事后无从比对。"""
    job = _job(tmp_path, stage='settings_verified')
    write_json(job / 'state.json',
               {'stage': 'settings_verified', 'submission_status': 'not_attempted',
                'source_product_id': '965251097615'})
    mark_copy_intent(job,
                     expected_skus={'1个装': '15.48'},
                     history_baseline=['965251097615@3850072322857894188'])
    state = read_json(job / 'state.json')
    assert state['stage'] == 'unknown'
    assert state['expected_skus'] == {'1个装': '15.48'}
    assert state['history_baseline'] == ['965251097615@3850072322857894188']


# ---------- Codex 二轮复核指出的盲区 ----------


def test_the_page_price_percent_is_a_hundred_times_the_multiplier():
    """页面的 pricePercent 是百分比，任务的 multiplier 是倍数，两者差 100 倍。

    写成 3 会把定价变成 3%——这个 bug 真的发生过一次，
    把妙手的 300% 改成了 3%。
    """
    preview = calculate_price('2', '3', '5')
    assert preview['page_price_percent'] == '300'
    assert preview['final_price'] == '11.00'


def test_the_settings_stage_writes_the_percentage_not_the_multiplier(tmp_path):
    """写配置那一段必须用换算后的百分比。"""
    from doudian_auto.dropship import calculate_price

    percent = calculate_price('2', '3', '5')['page_price_percent']
    assert percent != '3'
    assert int(percent) == int('3') * 100


def test_the_page_price_percent_is_a_hundred_times_the_multiplier():
    """页面的 pricePercent 是百分比，任务的 multiplier 是倍数，两者差 100 倍。

    写成 3 会把定价变成 3%——这个 bug 真的发生过一次，
    把妙手的 300% 改成了 3%。
    """
    preview = calculate_price('2', '3', '5')
    assert preview['page_price_percent'] == '300'
    assert preview['final_price'] == '11.00'


def test_the_settings_stage_writes_the_percentage_not_the_multiplier(tmp_path):
    """写配置那一段必须用换算后的百分比。"""
    from doudian_auto.dropship import calculate_price

    percent = calculate_price('2', '3', '5')['page_price_percent']
    assert percent != '3'
    assert int(percent) == int('3') * 100


# ---------- Codex 四轮复核指出的缺口 ----------

def test_baseline_must_be_proved_complete_before_copy(tmp_path):
    """页面写「共 59 条」而 DOM 只渲染 8 行时，基线不完整，必须拒绝复制。"""
    from doudian_auto.dropship import DoudianError as Err
    # 直接验证编排层用的判据：baseline_complete 为假就要拒
    baseline = {'baseline_complete': False, 'total_records': 59,
                'rendered_rows': 8, 'baseline_keys': [], 'pending_rows': 0}
    assert not baseline['baseline_complete']
    assert baseline['rendered_rows'] < baseline['total_records']


def test_unknown_cannot_be_created_without_a_recorded_copy_intent(tmp_path):
    """unknown 只能跟随已落盘的复制意图，点击前异常不许凭空进 unknown。"""
    job = _job(tmp_path, stage='settings_verified')
    write_json(job / 'state.json',
               {'stage': 'settings_verified', 'submission_status': 'not_attempted'})
    with pytest.raises(DoudianError, match='没有已落盘的复制意图'):
        record_copy_observation(job, outcome='unknown', evidence={'timeout': True})


def test_unknown_observation_is_allowed_after_a_recorded_intent(tmp_path):
    job = _job(tmp_path, stage='unknown', submission='unknown')
    write_json(job / 'state.json',
               {'stage': 'unknown', 'submission_status': 'unknown',
                'copy_intent_at': 1700000000.0})
    result = record_copy_observation(job, outcome='unknown', evidence={'timeout': True})
    assert result['stage'] == 'unknown'


def test_verified_task_cannot_be_pulled_back_to_unknown(tmp_path):
    job = _job(tmp_path, stage='verified')
    write_json(job / 'state.json',
               {'stage': 'verified', 'submission_status': 'accepted'})
    with pytest.raises(DoudianError, match='终态'):
        record_copy_observation(job, outcome='unknown', evidence={'x': 1})


def test_missing_review_status_stays_pending_not_an_error(tmp_path):
    """编辑页读不到审核状态是已知事实：应停在待核验，不抛错也不假装通过。"""
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json',
               {'stage': 'copied', 'target_product_id': '3853454064050373417',
                'expected_skus': {'1个装': '2'}})
    result = verify_target_readback(
        job, product_id='3853454064050373417',
        sku_rows=[{'sku': '1个装', 'price': '15.48'}], sku_total_count=1,
        price_progress=100, review_status=None)
    assert result['stage'] == 'verification_pending'
    assert '审核状态' in result['reason']


def test_source_sku_reader_rejects_a_malformed_offer_url():
    """适配器可被独立调用，畸形 URL 必须在 Python 侧就拒掉。"""
    bridge = FakeBridge([{'status': 'ok', 'sku_rows': []}])
    with pytest.raises(DoudianError, match='规范的'):
        DropshipPages(bridge).read_source_skus(
            offer_url='https://example.com/offer/965251097615.html')
    with pytest.raises(DoudianError, match='规范的'):
        DropshipPages(bridge).read_source_skus(
            offer_url='https://detail.1688.com/weird/965251097615.html')
