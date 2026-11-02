from doudian_auto.miaoshou_editor import MiaoshouEditor


def test_remembered_sku_tab_switches_once_inside_original_read_budget(monkeypatch):
    pid = '3848315786359865811'

    class Bridge:
        def __init__(self):
            self.calls = []

        def require_ready(self):
            pass

        def command(self, action, args):
            self.calls.append((action, args))
            return {'requests': []}

    bridge = Bridge()
    editor = MiaoshouEditor(bridge, '销霁百货', session='unit')
    monkeypatch.setattr(editor, '_mark_control', lambda op, product_id=None: op)
    monkeypatch.setattr(editor, '_visible_dom', lambda op, *args:
                        {'count': 0} if op == 'navigation_toggle' else
                        {'count': 1, 'selector': 'information_tab', 'identity': True})
    budgets = []

    def wait_tree(predicate, message, seconds=30):
        budgets.append(seconds)
        texts = (['您好【销霁百货】'] if len(budgets) == 1 else
                 ['ID：9999999999999999999 SKU/价格库存', f'ID：{pid} SKU/价格库存',
                  f'ID：{pid} SKU/价格库存', f'ID：{pid} 商品标题：'])
        for text in texts:
            snap = {'tree_text': text}
            before = sum(c == ('click', {'selector': 'information_tab'}) for c in bridge.calls)
            if predicate(snap):
                return snap
            if pid not in text:
                assert before == sum(c == ('click', {'selector': 'information_tab'}) for c in bridge.calls)
        raise AssertionError('never ready')

    monkeypatch.setattr(editor, '_wait_tree', wait_tree)
    assert '商品标题：' in editor.open_product(pid)['tree_text']
    assert bridge.calls.count(('click', {'selector': 'information_tab'})) == 1
    assert budgets == [30, 30]
    assert all('save' not in str(args).lower() for action, args in bridge.calls)
