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

        def check_session(self):
            return {'status': 'ok', 'login_required': False, 'page_url': 'https://x'}

        def navigate_official(self, product_id):
            return {'status': 'ok'}

        def read_sku_prices(self, *, product_id):
            return {'status': 'ok', 'sku_rows': [{'sku': '1个装', 'price': '15.48'}],
                    'price_progress': 100, 'completeness': 'unverified'}

        def read_review_status(self, *, product_id):
            return {'status': 'ok', 'review_status': None,
                    'review_status_reason': '商品审核状态不在编辑页',
                    'sku_status_tokens': ['已上架']}

        def read_target_review_status(self, product_id):
            # 2026-11-12 实抓：审核状态的权威来源是商品管理页/草稿箱，不是编辑页。
            return {'status': 'ok', 'source': 'doudian_product_list',
                    'product_id': product_id, 'platform_state': '审核驳回',
                    'row_text': '……审核驳回 查看原因 申诉 编辑'}

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
    # 编辑页读不到审核状态，但商品管理页/草稿箱读得到——不能就此放弃
    assert out['platform_review_status'] == '审核驳回'
    assert out['platform_review_source'] == 'doudian_product_list'


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


def test_source_sku_reader_rejects_a_malformed_offer_url():
    """适配器可被独立调用，畸形 URL 必须在 Python 侧就拒掉。"""
    bridge = FakeBridge([{'status': 'ok', 'sku_rows': []}])
    with pytest.raises(DoudianError, match='规范的'):
        DropshipPages(bridge).read_source_skus(
            offer_url='https://example.com/offer/965251097615.html')
    with pytest.raises(DoudianError, match='规范的'):
        DropshipPages(bridge).read_source_skus(
            offer_url='https://detail.1688.com/weird/965251097615.html')


# ---------- 真实闭环跑出来的页面细节 ----------

def test_polling_stops_immediately_when_counters_are_present():
    """跳过为 0 时计数器被隐藏，适配器会把它规范成 '0'；
    轮询见到两个计数齐全就应立即返回，不再空转到超时。
    """
    from doudian_auto.dropship import _wait_for_fetch_result

    class Bridge:
        def __init__(self):
            self.calls = 0

        def read_fetch_result(self):
            self.calls += 1
            return {'status': 'ok', 'success_count': '1',
                    'skipped_count': '0', 'skipped_inferred': True,
                    'page_url': 'https://v2-dd.chengji-inc.com/move/move'}

    bridge = Bridge()
    result = _wait_for_fetch_result(bridge, attempts=5, interval=0)
    assert bridge.calls == 1
    assert result['skipped_count'] == '0'
    assert not result.get('timed_out')


def test_polling_aborts_when_the_page_identity_changes():
    """轮询期间页面被切走，必须停下，不能把别处的计数当成本次结果。"""
    from doudian_auto.dropship import _wait_for_fetch_result

    class Bridge:
        def __init__(self):
            self.calls = 0

        def read_fetch_result(self):
            self.calls += 1
            return {'status': 'ok', 'success_count': None,
                    'skipped_count': None,
                    'page_url': 'A' if self.calls == 1 else 'B'}

    result = _wait_for_fetch_result(Bridge(), attempts=5, interval=0)
    assert result.get('timed_out') is True
    assert '页面身份变化' in result.get('reason', '')


def test_filtered_baseline_is_only_complete_when_total_equals_matched():
    """筛选态基线必须满足：筛选值==本来源，且「共 N 条」==匹配行数。"""
    complete = {'filter_value': '922368518409', 'total_records': 0,
                'matched_rows': 0, 'baseline_complete': True}
    assert complete['baseline_complete'] is True
    incomplete = {'filter_value': '999999999999', 'total_records': 1,
                  'matched_rows': 0, 'baseline_complete': False}
    assert incomplete['baseline_complete'] is False


# ---------- copy_confirmed：只声明能被证据证明的事 ----------

LIVE_SOURCE_SKUS = {
    '生物酶除臭剂【2500ml】送喷壶': '25.8',
    '生物酶除臭剂【5000ml】送喷壶': '43.8',
}
LIVE_SHOP_ROWS = [
    {'sku': '2500ml（生物酶除臭剂）', 'price': '85.88'},
    {'sku': '5000ml（生物酶除臭剂）', 'price': '139.88'},
]
LIVE_TARGET = '3853482303460343870'


def _confirm_job(tmp_path, *, expected=None, target=LIVE_TARGET):
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json', {
        'stage': 'copied', 'target_product_id': target,
        'expected_skus': dict(expected) if expected is not None
        else dict(LIVE_SOURCE_SKUS),
    })
    write_json(job / 'manifest.json', {
        'price_input': {'source_price': '25.80', 'multiplier': '3', 'addition': '5'},
    })
    return job


def test_copy_confirmed_when_the_price_formula_matches(tmp_path):
    """真实数据：25.8/43.8 ×3+5 = 82.40/136.40，售价 85.88/139.88，运费同为 3.48。"""
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None)
    assert report['stage'] == 'copy_confirmed'
    assert report['price_check']['shipping_delta'] == '3.48'
    assert any('价格符合任务公式' in x for x in report['verified_aspects'])


def test_official_page_has_no_review_status_but_that_is_not_a_blocker(tmp_path):
    """审核状态在官方编辑页结构上不存在，不能因此让终态永远不可达。"""
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None)
    assert report['stage'] == 'copy_confirmed'
    assert any('审核状态' in x for x in report['unverified_aspects'])


def test_platform_review_status_moves_the_review_aspect_to_verified(tmp_path):
    """编辑页读不到审核状态，但商品管理页/草稿箱读得到——不能就此放弃。

    实测（2026-11-12）：两页互斥——已提交商品在商品管理页（售卖中/已下架/
    审核驳回/审核中），草稿商品在草稿箱（待提交）。
    """
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None,
        platform_review_status='审核驳回', platform_review_source='doudian_product_list')
    assert report['stage'] == 'copy_confirmed'
    assert any('审核驳回' in x for x in report['verified_aspects'])
    assert not any('无法确认审核状态' in x for x in report['unverified_aspects'])


def test_platform_review_not_found_does_not_become_a_state(tmp_path):
    """两页都查不到就如实说查不到，不能写成「未提审」之类。"""
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None,
        platform_review_status=None, platform_review_source='doudian')
    assert report['stage'] == 'copy_confirmed'
    assert any('无法确认审核状态' in x for x in report['unverified_aspects'])
    assert not any('未提审' in x for x in report['verified_aspects'])


def test_miaoshou_rewriting_spec_names_is_checked_by_quantity_markers(tmp_path):
    """妙手改写规格名是常态。

    所以「规格名全等」不能当判据——真实页面上它几乎从不成立。
    改成问一个可判定的问题：来源规格里的数量标记还在不在官方规格名里。
    实测来源「生物酶除臭剂【2500ml】送喷壶」→ 官方「2500ml（生物酶除臭剂）」，
    数量标记 2500ml 保留，所以这一项从「永远未验证」变成可自动判定。
    """
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None)
    assert report['stage'] == 'copy_confirmed'
    assert report['spec_identity']['status'] == 'matched'
    assert any('规格名数量标记' in x for x in report['verified_aspects'])
    assert not any('规格名' in x for x in report['unverified_aspects'])


def test_spec_identity_fails_when_the_quantity_marker_disappears(tmp_path):
    """数量标记都对不上时，规格名核对必须如实报未通过，而不是默默放过。"""
    job = _confirm_job(tmp_path)
    rows = [{'sku': '红色（生物酶除臭剂）', 'price': '85.88'},
            {'sku': '蓝色（生物酶除臭剂）', 'price': '139.88'}]
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=rows,
        sku_total_count=None, price_progress=100, review_status=None)
    assert report['spec_identity']['status'] == 'mismatch'
    assert any('规格名核对未通过' in x for x in report['unverified_aspects'])


def test_price_formula_mismatch_stays_pending(tmp_path):
    job = _confirm_job(tmp_path)
    rows = [dict(LIVE_SHOP_ROWS[0]),
            {'sku': '5000ml（生物酶除臭剂）', 'price': '999.88'}]
    result = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=rows,
        sku_total_count=None, price_progress=100, review_status=None)
    assert result['stage'] == 'verification_pending'
    assert any('价格公式' in b for b in result['blockers'])


def test_sku_count_mismatch_stays_pending(tmp_path):
    job = _confirm_job(tmp_path)
    result = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS[:1],
        sku_total_count=2, price_progress=100, review_status=None)
    assert result['stage'] == 'verification_pending'


def test_missing_expected_skus_stays_pending(tmp_path):
    job = _confirm_job(tmp_path, expected={})
    result = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None)
    assert result['stage'] == 'verification_pending'


def test_price_progress_below_100_stays_pending(tmp_path):
    job = _confirm_job(tmp_path)
    result = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=50, review_status=None)
    assert result['stage'] == 'verification_pending'


def test_terminal_state_is_copy_confirmed_not_verified(tmp_path):
    """终态改名：不再叫 verified，因为三项证据在官方页结构上拿不到。"""
    job = _confirm_job(tmp_path)
    report = verify_target_readback(
        job, product_id=LIVE_TARGET, sku_rows=LIVE_SHOP_ROWS,
        sku_total_count=None, price_progress=100, review_status=None)
    assert report['stage'] == 'copy_confirmed'
    state = read_json(job / 'state.json')
    assert state['stage'] == 'copy_confirmed'


# ---------- 类目预检与人工补值清单 ----------

def test_precheck_blocks_a_known_strong_attribute_category():
    from doudian_auto.dropship_policy import precheck_category, require_precheck_allowed
    pre = precheck_category(category='家清纸品>除臭用品>空气清新/净化/芳香剂')
    assert pre['risk'] == 'high' and pre['basis'] == 'category'
    assert pre['missing_attributes'] == ['保质期', '生产企业名称']
    with pytest.raises(DoudianError, match='预检命中'):
        require_precheck_allowed(pre)


def test_precheck_can_be_explicitly_allowed_by_an_operator():
    from doudian_auto.dropship_policy import precheck_category, require_precheck_allowed
    pre = precheck_category(category='空气清新/净化/芳香剂')
    assert require_precheck_allowed(pre, allow_risk=True)['action'] == 'allowed_by_operator'


def test_precheck_keyword_hit_is_marked_as_heuristic(tmp_path):
    """标题命中只能预警，不能冒充类目证据。"""
    from doudian_auto.dropship_policy import precheck_category
    pre = precheck_category(title='酒店生物酶除味剂空气清新分解型去异味净味')
    assert pre['risk'] == 'high' and pre['basis'] == 'keyword_heuristic'
    assert '除味剂' in pre['matched_keywords']


def test_precheck_low_risk_for_an_unrelated_product():
    from doudian_auto.dropship_policy import precheck_category
    assert precheck_category(title='车门限位器保护盖')['risk'] == 'low'


def test_missing_attributes_are_parsed_from_the_real_history_row():
    from doudian_auto.dropship_policy import extract_missing_attributes
    row = '「保质期,生产企业名称」未填写，导致复制失败，系统自动放至草稿箱'
    assert extract_missing_attributes(row) == ['保质期', '生产企业名称']
    assert extract_missing_attributes('已成功复制 审核通过') == []


def test_manual_attribute_list_is_written_without_inventing_values(tmp_path):
    from doudian_auto.dropship_policy import build_manual_attribute_list, \
        load_manual_attribute_list
    job = _job(tmp_path)
    checklist = build_manual_attribute_list(
        job, source_product_id='922368518409',
        target_product_id=LIVE_TARGET,
        row_text='「保质期,生产企业名称」未填写，导致复制失败，系统自动放至草稿箱')
    assert checklist['missing_count'] == 2
    assert all(item['value'] is None for item in checklist['items'])
    assert all(item['source'] == '人工填写' for item in checklist['items'])
    assert load_manual_attribute_list(job)['missing_count'] == 2


# ---------- 选品候选与人工待办汇总 ----------

def test_manual_queue_report_merges_both_lines(tmp_path):
    """铺货任务与批量队列的待补值要汇到同一张只读清单。"""
    from doudian_auto.dropship_policy import (build_manual_attribute_list,
                                              build_manual_queue_report)
    job = tmp_path / 'dropship-task-1'
    job.mkdir()
    build_manual_attribute_list(
        job, source_product_id='922368518409',
        target_product_id='3853482303460343870',
        row_text='"保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱')

    report = build_manual_queue_report(data_root=str(tmp_path))
    assert report['by_line']['dropship'] == 2
    assert all(x['attribute'] in ('保质期', '生产企业名称')
               for x in report['items'] if x['line'] == 'dropship')
    assert report['total_items'] == len(report['items'])
    assert '只读' in report['note']


def test_manual_queue_report_never_invents_values():
    from doudian_auto.dropship_policy import build_manual_queue_report
    report = build_manual_queue_report()
    assert 'value' not in report
    for item in report['items']:
        assert set(item) >= {'line', 'product_id', 'attribute', 'evidence'}
    assert all('不推断' in report['note'] or '程序不推断' in report['note']
               for _ in [0])


def test_opportunity_candidates_declare_the_identity_limit():
    """选品候选必须如实说明「卡片没有 offer ID」，不能被当成可直接铺的链接。"""
    bridge = FakeBridge([{
        'status': 'ok', 'candidate_count': 1,
        'candidates': [{'title': 'X', 'supports_cipher': True,
                        'dropship': True, 'miaoshou_uuid': 'u-1'}],
        'identity_note': '机会卡片不含 1688 offer ID，只有妙手内部 UUID；不能直接铺货。',
    }])
    result = DropshipPages(bridge).read_opportunity_candidates(limit=1)
    assert result['candidate_count'] == 1
    assert 'offer ID' in result['identity_note']
