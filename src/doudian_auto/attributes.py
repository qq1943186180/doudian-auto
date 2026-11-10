"""Write category attributes that the user has explicitly supplied, then read them back.

Scope is deliberately narrow. Only text inputs and single-select dropdowns are written,
because those two shapes were observed on the real page and have an unambiguous success
signal. Multi-select is refused: during the publish acceptance run, picking a second
option did not accumulate, and shipping a write path whose result cannot be predicted is
worse than making the user do that field by hand.

No value is ever invented here. Every value must arrive from the caller, who is expected
to have gotten it from the user. A blank or placeholder value is skipped, never guessed.
"""

from __future__ import annotations

import time

from .errors import DoudianError

# Fields this module refuses to write, with the reason surfaced to the caller.
UNSUPPORTED_KINDS = {
    'multi': '多选下拉暂不支持（选项中可能存在交互差异，需人工确认）',
    'unknown': '控件类型未识别，需人工处理',
}


def _control(editor, manifest, name):
    """Describe one attribute on the currently open page, or explain why it cannot be used."""
    info = editor.dom('attribute_control', manifest, name=name)
    if info.get('error') == 'attribute_not_unique':
        raise DoudianError('attribute_not_unique',
                           f'页面上“{name}”的属性框不唯一（找到 {info.get("count")} 个），停止。')
    if info.get('error'):
        raise DoudianError(info['error'], f'无法定位属性“{name}”。')
    return info


def _click(editor, selector):
    editor.bridge.command('click', {'selector': selector})


def apply_attributes(editor, manifest, values, *, settle=1.2):
    """Write the given {attribute_name: value} pairs, verifying each one read-backs exactly.

    Returns a per-field report. Stops at the first field whose result cannot be confirmed,
    because a partially applied attribute set is a fact error, not a partial success.
    """
    results = []
    for name, value in values.items():
        value = (value or '').strip()
        if not value or value == '待确认':
            results.append({'name': name, 'written': False, 'reason': '值为空或待确认，跳过'})
            continue

        before = _control(editor, manifest, name)
        kind = before.get('kind')
        if kind in UNSUPPORTED_KINDS:
            results.append({'name': name, 'written': False, 'kind': kind,
                            'reason': UNSUPPORTED_KINDS[kind]})
            continue
        if before.get('disabled'):
            results.append({'name': name, 'written': False, 'kind': kind,
                            'reason': '控件被禁用'})
            continue

        current = (before.get('current') or '').strip()
        if current and current not in ('请选择', '') and current != value:
            # Overwriting an existing different value is a replacement, not a fill.
            results.append({'name': name, 'written': False, 'kind': kind,
                            'reason': f'已有值“{current}”，与目标“{value}”不同，不覆盖'})
            continue

        try:
            if kind == 'text':
                editor.bridge.command('fill', {'selector': before['marked'], 'value': value})
                time.sleep(0.6)
            elif kind == 'single':
                _click(editor, before['marked'])
                time.sleep(settle)
                option = editor.dom('attribute_options', manifest, name=name, value=value)
                if option.get('error') == 'option_not_unique':
                    results.append({'name': name, 'written': False, 'kind': kind,
                                    'reason': f'候选项不唯一，可选：{option.get("candidates", [])[:12]}'})
                    continue
                if option.get('error'):
                    results.append({'name': name, 'written': False, 'kind': kind,
                                    'reason': option['error']})
                    continue
                _click(editor, option['selector'])
                time.sleep(settle)
            else:
                results.append({'name': name, 'written': False, 'kind': kind, 'reason': '未支持'})
                continue
        except DoudianError as exc:
            results.append({'name': name, 'written': False, 'kind': kind, 'reason': exc.code})
            continue

        after = _control(editor, manifest, name)
        got = (after.get('current') or '').strip()
        ok = got == value
        results.append({'name': name, 'written': ok, 'kind': kind,
                        'before': current, 'wanted': value, 'readback': got,
                        'reason': None if ok else '读回值与目标不一致，未确认写入'})
        if not ok:
            break

    return results


def verify_after_reopen(editor, manifest, values):
    """Reopen the page and confirm each written attribute survived, independent of the DOM cache."""
    editor.open(manifest, fresh=True)
    checked = []
    for name, value in values.items():
        value = (value or '').strip()
        if not value or value == '待确认':
            continue
        try:
            info = _control(editor, manifest, name)
        except DoudianError as exc:
            checked.append({'name': name, 'ok': False, 'reason': exc.code})
            continue
        got = (info.get('current') or '').strip()
        checked.append({'name': name, 'ok': got == value, 'wanted': value, 'readback': got})
    return checked
