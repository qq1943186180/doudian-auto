"""机会铺货的安全边界回归测试。

这些用例守住的都是「错了会出事」的边界：结果未知时不许重试、活着的锁不许清、
配置读回不一致必须停、页面定位不唯一必须失败关闭。功能happy path 由真实页面验收覆盖。
"""
from pathlib import Path

import pytest

from doudian_auto.dropship import (
    calculate_price,
    mark_copy_intent,
    prepare_task,
    record_configuration_audit,
    record_copy_observation,
    verify_target_readback,
    _acquire_task_lock,
)
from doudian_auto.dropship_pages import DropshipPages
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import write_json


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
    with pytest.raises(DoudianError, match='只允许只读核查'):
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
    with pytest.raises(DoudianError, match='商品 ID 读回不完整'):
        record_copy_observation(job, outcome='copied', target_product_id='123')


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
        verify_target_readback(job, sku_rows=[{'sku': 'x', 'price': '1'}], review_status='待审核')


def test_verify_reports_review_status_without_inferring(tmp_path):
    job = _job(tmp_path, stage='copied')
    write_json(job / 'state.json', {'stage': 'copied', 'target_product_id': '3853454064050373417'})
    report = verify_target_readback(
        job, sku_rows=[{'sku': '1个装', 'price': '15.48'}], review_status='待审核')
    assert report['review_status_read_only'] == '待审核'
    assert report['sku_rows'][0]['price'] == '15.48'


# ---------- 任务创建 ----------

def test_prepare_rejects_non_https_offer(tmp_path):
    with pytest.raises(DoudianError, match='HTTPS'):
        prepare_task(source_product_id='965251097615', offer_url='http://detail.1688.com/x',
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
                          'sku_rows': [{'sku': '1个装', 'price': '15.48'}]}])
    result = DropshipPages(bridge).read_sku_prices(
        product_id='3853454064050373417', sku_names=['1个装'])
    assert result['sku_rows'][0]['price'] == '15.48'
    # 价格取自 input 的 value
    assert 'placeholder="请输入"' in bridge.calls[0]
    assert 'inputs[0].value' in bridge.calls[0]
    # 行文本只用于定位 SKU 行，不作为价格来源
    assert '.includes(name)' in bridge.calls[0]
    # 不能出现把行文本当价格读的写法
    assert 'rowText' not in bridge.calls[0].replace('.includes(name)', '')
