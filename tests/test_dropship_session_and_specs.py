"""会话掉线闸门、规格名数量标记核对、人工待办口径的回归测试。

这三块都是 2026-11-12 这一轮加的，共同点：
断言必须钉在**真实观测**上（真实页面跳转、真实复制历史行、真实队列错误原文），
不是自造的 mock。
"""
from pathlib import Path

import pytest

from doudian_auto.dropship import (
    _check_spec_identity,
    _require_shop_session,
)
from doudian_auto.dropship_policy import (
    build_manual_attribute_list,
    classify_blocked_reason,
    extract_missing_attribute_names,
    parse_history_row_facts,
)
from doudian_auto.errors import DoudianError


# ---------- 会话掉线闸门 ----------

def test_login_expired_fails_closed_before_any_page_write():
    """会话过期时页面会跳登录页。

    这时继续跑只会得到「当前页面不是预期的XX页」，根因被埋掉；
    掉线只能由人重新登录，程序不能代登录，也不能在登录页上重放写操作。
    """
    class LoggedOut:
        def check_session(self):
            return {'status': 'ok', 'login_required': True,
                    'page_url': 'https://fxg.jinritemai.com/login/common?next=x',
                    'login_marker': '验证码登录'}

    with pytest.raises(DoudianError, match='会话已过期'):
        _require_shop_session(LoggedOut(), page_name='搬家设置页')


def test_login_guard_passes_when_the_session_is_alive():
    class Alive:
        def check_session(self):
            return {'status': 'ok', 'login_required': False,
                    'page_url': 'https://v2-dd.chengji-inc.com/move/move'}

    assert _require_shop_session(Alive(), page_name='搬家设置页')['login_required'] is False


# ---------- 规格名：数量标记包含关系 ----------

def test_spec_identity_matches_both_real_copies():
    """两次真实铺货：妙手改写了规格展示名，但数量标记都保留。

      来源「4个装」                      → 官方「极氪车门限位器-4个装」
      来源「生物酶除臭剂【2500ml】送喷壶」 → 官方「2500ml（生物酶除臭剂）」
    """
    first = _check_spec_identity(
        {'4个装': '6', '1个装': '2'},
        {'极氪车门限位器-4个装': '27.48', '极氪车门限位器-1个装': '15.48'})
    assert first['status'] == 'matched'

    second = _check_spec_identity(
        {'生物酶除臭剂【2500ml】送喷壶': '25.8', '生物酶除臭剂【5000ml】送喷壶': '43.8'},
        {'2500ml（生物酶除臭剂）': '85.88', '5000ml（生物酶除臭剂）': '139.88'})
    assert second['status'] == 'matched'


def test_spec_identity_is_not_checkable_without_a_quantity_marker():
    """「红色」这种规格没有数量标记，就不能说「核对通过」，只能说无法核对。"""
    result = _check_spec_identity({'红色': '5'}, {'深红色（经典款）': '15'})
    assert result['status'] == 'partial'
    assert result['not_checkable'][0]['source_spec'] == '红色'


def test_spec_identity_reports_a_mismatch_when_the_marker_disappears():
    result = _check_spec_identity(
        {'2500ml（生物酶除臭剂）': '25.8'}, {'5000ml（生物酶除臭剂）': '85.88'})
    assert result['status'] == 'mismatch'
    assert result['unmatched'][0]['source_spec'] == '2500ml（生物酶除臭剂）'


# ---------- 复制历史行解析（真实行文） ----------

REAL_HISTORY_ROW = (
    '阿里巴巴酒店生物酶除味剂空气清新分解型去异味净味卫生间房间专用除臭剂\n'
    '发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂\n'
    '1688分销\n'
    '明丞生物科技有限公司（明丞生物科技有限公司）\n'
    '源ID：\n922368518409\n'
    '默认配置\n'
    '已成功复制\n'
    '"保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱\n'
    '2026-11-12 01:40\n'
    '商品ID：\n3853482303460343870\n'
    '草稿箱\n'
    '未提审\n'
    '销量：--\n'
    '商品快速编辑\n'
    '去抖店编辑\n'
    '更多')


def test_history_row_facts_are_parsed_from_the_real_row():
    """真实复制历史行（2026-11-12，商品 3853482303460343870）。

    这些字段以前采到了却没用，人工补值时还得自己翻页面。
    """
    facts = parse_history_row_facts(REAL_HISTORY_ROW)
    assert facts['category'] == '家清纸品>除臭用品>空气清新/净化/芳香剂'
    assert facts['source_supplier'] == '明丞生物科技有限公司'
    assert facts['source_product_id'] == '922368518409'
    assert facts['product_id'] == '3853482303460343870'
    assert '草稿箱' in facts['target_states']
    assert '未提审' in facts['target_states']


def test_missing_attribute_names_cover_both_real_error_shapes():
    """两种真实失败原文都要能解析出属性名。"""
    preflight = ('preflight_exception: required_attributes_missing; '
                 '平台必填类目属性缺失：安装方式；需真实资料补齐后续办，未上传或保存。; '
                 'missing_fields=["安装方式"]')
    assert extract_missing_attribute_names(preflight) == ['安装方式']

    miaoshou = ('妙手任务27418021已完成且失败：缺安装方式；官方另缺承重、适配基面类型，'
                '待真实参数。保存记录保持只读隔离。')
    assert extract_missing_attribute_names(miaoshou) == ['安装方式', '承重', '适配基面类型']

    # 没有属性名的原文不能被塞一个占位名进去
    assert extract_missing_attribute_names(
        'preflight_exception: doudian_draft_or_rejected; 官方页面存在草稿或驳回。; '
        'missing_fields=[]') == []


def test_blocked_reasons_are_classified_into_machine_readable_classes():
    """43 件 blocked 的真实原因分布必须能被机器分类，人工才能分诊。"""
    assert classify_blocked_reason(
        'preflight_exception: required_attributes_missing; 平台必填类目属性缺失：尺寸；'
    )['reason_class'] == 'missing_required_attributes'
    assert classify_blocked_reason(
        'external_work_requires_rebaseline')['reason_class'] == 'needs_rebaseline'
    assert classify_blocked_reason(
        'writer_image_slots_incomplete: 官方及妙手均为4张主图/4张详情'
    )['reason_class'] == 'image_slots_insufficient'
    assert classify_blocked_reason(
        'doudian_product_deleted: 编辑页返回「商品不存在或已彻底删除」'
    )['reason_class'] == 'product_deleted'
    # 认不出就如实说认不出，不能硬塞进某个类
    assert classify_blocked_reason('完全没见过的新错误')['reason_class'] == 'unclassified'


def test_manual_attribute_list_carries_the_category_and_supplier_reference(tmp_path):
    """补值清单要带上类目与来源供应商（只作参考，不是答案）。"""
    job = tmp_path / 'task'
    job.mkdir()
    checklist = build_manual_attribute_list(
        job, source_product_id='922368518409',
        target_product_id='3853482303460343870', row_text=REAL_HISTORY_ROW)
    assert checklist['category'] == '家清纸品>除臭用品>空气清新/净化/芳香剂'
    assert checklist['source_supplier'] == '明丞生物科技有限公司'
    names = {item['attribute']: item for item in checklist['items']}
    assert set(names) == {'保质期', '生产企业名称'}
    # 值一律留空：程序不猜值
    assert all(item['value'] is None for item in checklist['items'])
    assert names['生产企业名称']['reference_supplier'] == '明丞生物科技有限公司'
    assert '仅作参考' in names['生产企业名称']['reference_note']
    assert 'reference_supplier' not in names['保质期']
