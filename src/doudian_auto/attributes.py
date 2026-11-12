"""Write category attributes that the user has explicitly supplied, then read them back.

Scope is deliberately narrow. Only text inputs and single-select dropdowns are written,
because those two shapes were observed on the real page and have an unambiguous success
signal. Multi-select is refused: during the publish acceptance run, picking a second
option did not accumulate, and shipping a write path whose result cannot be predicted is
worse than making the user do that field by hand.

A measure attribute (a number plus a unit dropdown in one box, measured on 保质期) is
written as two ordinary steps: fill the number, then pick the unit. Both steps are
read back from the page, and the pair is only accepted when the composed value equals
the requested one.

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


def _split_measure(value):
    """Split a requested measure value into its number and its unit.

    The unit is whatever follows the leading digits, so the caller can write
    "12个月" for a shelf life of twelve months. Nothing is inferred: a value
    without digits, or with more than one number, is refused rather than guessed.
    """
    text = (value or '').strip()
    digits = ''
    rest = text
    while rest and rest[0].isdigit():
        digits += rest[0]
        rest = rest[1:]
    unit = rest.strip()
    if not digits or not unit:
        return None, None
    # A value such as "12个月/3" is ambiguous: the unit must not carry digits.
    if any(ch.isdigit() for ch in unit):
        return None, None
    return digits, unit


def _apply_measure(editor, manifest, name, value, *, settle=1.2):
    """Fill a measure attribute: the number first, then the unit dropdown.

    The order matters. The platform's dropdown re-renders the measure row when a
    unit is chosen, and a measured run confirmed that picking the unit afterwards
    leaves the number in place while the reverse order does not. Both halves are
    read back and the composed value must equal the requested one.
    """
    number, unit = _split_measure(value)
    if number is None:
        return {'name': name, 'written': False, 'kind': 'measure',
                'reason': f'值“{value}”不是「数值+单位」形式，未填写'}
    control = _control(editor, manifest, name)
    if control.get('kind') != 'measure':
        return {'name': name, 'written': False, 'kind': control.get('kind'),
                'reason': '控件形态已变，不是数值+单位复合控件，未填写'}
    if control.get('disabled'):
        return {'name': name, 'written': False, 'kind': 'measure', 'reason': '控件被禁用'}
    current = (control.get('current') or '').strip()
    if current and current != value:
        return {'name': name, 'written': False, 'kind': 'measure',
                'reason': f'已有值“{current}”，与目标“{value}”不同，不覆盖'}
    candidates = []
    try:
        editor.bridge.command('fill', {'selector': control['marked'], 'value': number})
        time.sleep(0.6)
        # Typing re-renders the measure row, and the re-render can replace the unit
        # dropdown node that carries the mark. Re-read the control so the click uses a
        # mark that is on the live node instead of a stale one.
        control = _control(editor, manifest, name)
        _click(editor, control['unit_marked'])
        time.sleep(settle)
        # Read the platform's own unit list first, so a unit that does not exist
        # stops the run instead of being written into the wrong field.
        listing = editor.dom('attribute_unit_options', manifest, name=name)
        candidates = listing.get('candidates') or []
        if unit not in candidates:
            return {'name': name, 'written': False, 'kind': 'measure',
                    'reason': f'单位“{unit}”不在页面候选项里，未填写',
                    'candidates': candidates}
        option = editor.dom('attribute_unit_options', manifest, name=name, value=unit)
        if option.get('error'):
            return {'name': name, 'written': False, 'kind': 'measure',
                    'reason': option.get('error'), 'candidates': candidates}
        _click(editor, option['selector'])
        time.sleep(settle)
    except DoudianError as exc:
        return {'name': name, 'written': False, 'kind': 'measure',
                'reason': exc.code, 'candidates': candidates}
    after = _control(editor, manifest, name)
    got = (after.get('current') or '').strip()
    ok = got == value
    return {'name': name, 'written': ok, 'kind': 'measure',
            'before': current, 'wanted': value, 'readback': got,
            'number': after.get('number_value'), 'unit': after.get('unit_value'),
            'reason': None if ok else '读回值与目标不一致，未确认写入'}


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
        if kind == 'measure':
            outcome = _apply_measure(editor, manifest, name, value, settle=settle)
            results.append(outcome)
            if not outcome.get('written'):
                break
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
