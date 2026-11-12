"""审核状态读取路径、机会商品落地页契约、复制历史全量采集与行解析。

这里的每条断言都对应 2026-11-12 的一次真实观测，行文是逐字抄下来的，
不是编的样例。行文里出现的商品 ID 与类目路径都来自本店真实复制历史。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from doudian_auto.dropship_pages import DropshipPages  # noqa: E402
from doudian_auto.dropship_policy import parse_history_row_facts  # noqa: E402
from doudian_auto.errors import DoudianError  # noqa: E402


# 实测行文（DOM innerText 原样，含换行）
REAL_ROW_DRAFT = """阿里巴巴酒店生物酶除味剂空气清新分解型去异味净味卫生间房间专用除臭剂
发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂
1688分销
明丞生物科技有限公司（明丞生物科技有限公司）
源ID：
922368518409
默认配置
已成功复制
"保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱
2026-11-12 01:40
商品ID：
3853482303460343870
草稿箱
未提审
销量：--
商品快速编辑
去抖店编辑
更多"""

# 供应商是**纯名称**、没有「（店铺名）」的那种形态
REAL_ROW_PLAIN_SUPPLIER = """阿里巴巴3号IC钥匙扣复旦m1芯片门禁卡房东物业小区电梯卡非接触式感应卡
发布类目：全屋智能>智能家居系统>楼宇智能系统>门禁智能卡
1688分销
瑞安市激濠五金商行
源ID：
1074500000000
默认配置
已成功复制
2026-10-24 16:36
商品ID：
3850071900000000001
已下架
审核通过
销量：0
商品快速编辑
去抖店编辑
更多"""

# 「翻新复制」行的源 ID 键是「新源ID：」，而且这一行没有供应商
REAL_ROW_RENEW = """阿里巴巴亚马逊越野车载汽车绑带灭火器固定带牧马人灭火器魔术贴绑带架
发布类目：汽车零配件>美容/维修/汽保工具>汽车维修保养工具>拖车绳/网/绑带
翻新复制
新源ID：
585742164902
默认配置
审核通过
已成功复制
2026-10-24 16:36
商品ID：
3850071900000000002
已下架
审核通过
销量：0
商品快速编辑
去抖店编辑
更多"""


def _collapse(row):
    """把多行行文折成单行——历史行有时就是这样传进来的。"""
    return ' '.join(part.strip() for part in row.split('\n') if part.strip())


def test_category_stops_at_copy_type_marker_in_collapsed_text():
    """类目正则原来在单行文本下会把整行都吃成类目。

    旧实现 `([^\\n\\r]+)` 遇到被折叠成单行的历史行时，类目会变成
    「家清纸品>… 明丞生物… 源ID： 922368518409 已成功复制 ……」一整串。
    """
    facts = parse_history_row_facts(_collapse(REAL_ROW_DRAFT))
    assert facts['category'] == '家清纸品>除臭用品>空气清新/净化/芳香剂'
    assert '源ID' not in facts['category']
    assert '明丞生物' not in facts['category']


def test_category_matches_between_multiline_and_collapsed_forms():
    """两种文本形态必须解析出同样的事实，否则统计口径会随取数方式漂移。"""
    multiline = parse_history_row_facts(REAL_ROW_DRAFT)
    collapsed = parse_history_row_facts(_collapse(REAL_ROW_DRAFT))
    for key in ('category', 'source_supplier', 'source_shop', 'copy_type',
                'product_id', 'source_product_id', 'platform_states',
                'platform_audit_state', 'miaoshou_audit_state'):
        assert multiline[key] == collapsed[key], key


def test_supplier_plain_name_without_parentheses():
    """58 条里有 8 条供应商是纯名称，原来只认「名称（店铺名）」就全丢了。"""
    facts = parse_history_row_facts(REAL_ROW_PLAIN_SUPPLIER)
    assert facts['source_supplier'] == '瑞安市激濠五金商行'
    assert facts['source_shop'] is None


def test_supplier_with_shop_suffix_keeps_both_parts():
    facts = parse_history_row_facts(REAL_ROW_DRAFT)
    assert facts['source_supplier'] == '明丞生物科技有限公司'
    assert facts['source_shop'] == '明丞生物科技有限公司'


def test_renew_copy_row_uses_the_new_source_id_key():
    """「翻新复制」行的源 ID 键是「新源ID：」，旧正则只认「源ID：」会漏掉。"""
    facts = parse_history_row_facts(REAL_ROW_RENEW)
    assert facts['source_product_id'] == '585742164902'
    assert facts['copy_type'] == '翻新复制'
    # 这一行确实没有供应商，不能把别的字段当供应商
    assert facts['source_supplier'] is None


def test_platform_and_miaoshou_states_are_separated_by_position():
    """妙手侧「审核通过」在商品 ID 之前，抖店侧「审核通过」在商品 ID 之后。

    混在一起统计会得出「未提审+审核通过+已下架」这种三词组合，无从判断谁是谁。
    """
    facts = parse_history_row_facts(REAL_ROW_DRAFT)
    assert facts['platform_states'] == ['草稿箱']
    assert facts['platform_audit_state'] == '未提审'
    assert facts['miaoshou_audit_state'] is None
    assert facts['target_states'] == ['草稿箱', '未提审']
    assert facts['copy_state'] == '已成功复制'
    assert facts['failure_reason'] == (
        '"保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱')


def test_miaoshou_audit_state_is_read_before_the_product_id():
    facts = parse_history_row_facts(REAL_ROW_PLAIN_SUPPLIER)
    assert facts['platform_states'] == ['已下架']
    assert facts['platform_audit_state'] == '审核通过'
    assert facts['miaoshou_audit_state'] is None


def test_failure_reason_is_captured_verbatim():
    facts = parse_history_row_facts(REAL_ROW_DRAFT)
    assert '保质期' in facts['failure_reason']
    assert '生产企业名称' in facts['failure_reason']


class _Bridge:
    def __init__(self, results):
        self.results = results
        self.calls = []
        self.navigations = []

    def command(self, action, args=None):
        self.navigations.append((action, args))
        return {'status': 'ok'}

    def evaluate(self, code):
        self.calls.append(code)
        value = self.results[len(self.calls) - 1]
        return value


def test_not_found_is_an_observation_not_a_layout_change():
    """「查无此项」是观测结论，不能当成结构变化抛错。"""
    pages = DropshipPages(_Bridge([{'status': 'not_found', 'reason': 'product_id_not_in_list'}]))
    result = pages.read_official_product_status('3850071994200621373', navigate=False)
    assert result['status'] == 'not_found'
    assert result['reason'] == 'product_id_not_in_list'


def test_unknown_status_still_fails_closed():
    pages = DropshipPages(_Bridge([{'status': 'weird'}]))
    with pytest.raises(DoudianError):
        pages.read_official_product_status('3850071994200621373', navigate=False)


def test_target_review_status_falls_back_to_the_draft_box():
    """商品管理页查不到就查草稿箱——两页互斥，草稿商品只出现在草稿箱。"""
    bridge = _Bridge([
        {'status': 'not_found', 'reason': 'product_id_not_in_list'},
        {'status': 'ok', 'platform_state': '待提交', 'row_text': 'ID:3853482303460343870 待提交'},
    ])
    pages = DropshipPages(bridge)
    result = pages.read_target_review_status('3853482303460343870')
    assert result['status'] == 'ok'
    assert result['source'] == 'doudian_draft_box'
    assert result['platform_state'] == '待提交'


def test_target_review_status_reports_not_found_without_inventing_a_state():
    """两页都查不到就说查不到，不能推断成「未提审」。"""
    bridge = _Bridge([
        {'status': 'not_found', 'reason': 'product_id_not_in_list'},
        {'status': 'not_found', 'reason': 'product_id_not_in_draft'},
    ])
    pages = DropshipPages(bridge)
    result = pages.read_target_review_status('9999999999999999999')
    assert result['status'] == 'not_found'
    assert result['platform_state'] is None
    assert '不能推断' in result['note']
