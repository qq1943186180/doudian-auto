"""Validate the recorded pre-input failure of the audited legacy Ego writer.

This is an evidence import, never a browser retry. Unknown transport failures
and errors after native input cannot produce this certificate.
"""

import hashlib
import json
import re
from pathlib import Path

from .errors import DoudianError

# Git blob 8ef0e2a:src/doudian_auto/ego_runtime.mjs. Its one occurrence of
# ego_target_not_unique is raised before focus emulation and page.mouse.click.
AUDITED_RUNTIME_SHA256 = {'d0b5d90a116412425e3f4b53f00bc8b9adbb3ce4602504ad618902438ad3768f'}


def verify_native_preclick_trace(trace, intent, outcome, *, data_root):
    def refuse():
        raise DoudianError('preclick_recovery_not_proven',
                           '原生保存动作的点击前失败记录不完整，保持只读隔离。')

    try:
        if not isinstance(trace, dict):
            refuse()
        runtime = Path(trace['runtime_path']).read_bytes()
        digest = hashlib.sha256(runtime).hexdigest()
        if digest not in AUDITED_RUNTIME_SHA256 or trace['runtime_sha256'] != digest:
            refuse()
        session = trace['session']
        root = Path(data_root) / 'ego-sessions' / hashlib.sha256(session.encode()).hexdigest()[:24]
        token = trace['round_id']
        arm_token = trace['arm_round_id']
        if not all(re.fullmatch('[0-9a-f]{32}', value) for value in (token, arm_token)):
            refuse()

        def load(round_id):
            request = root / (round_id + '.json')
            response = root / (round_id + '.result.json')
            return request, response, json.loads(request.read_text(encoding='utf-8')), json.loads(response.read_text(encoding='utf-8'))

        request, response, req, res = load(token)
        if (hashlib.sha256(request.read_bytes()).hexdigest() != trace['request_sha256'] or
                hashlib.sha256(response.read_bytes()).hexdigest() != trace['result_sha256'] or
                req['session'] != session or req['action'] != 'click' or
                res.get('ok') is not False or
                res.get('error') != {'code': 'ego_target_not_unique',
                                     'message': 'No unique actionable current DOM target.'}):
            refuse()
        selector = (req.get('args') or {}).get('selector', '')
        match = re.fullmatch(r'\[data-codex-miao-batch="(miao-batch-final-[0-9a-f]{32})"\]', selector)
        if not match:
            refuse()
        start, end = intent['created_at'], outcome['occurred_at']
        if not start <= request.stat().st_mtime <= response.stat().st_mtime <= end <= start + 30:
            refuse()
        if json.loads(outcome['detail']) != {'state': 'unknown', 'error': 'ego_target_not_unique'}:
            refuse()
        arm_request, arm_response, arm_req, arm_res = load(arm_token)
        arm_code = (arm_req.get('args') or {}).get('code', '')
        if (arm_req['action'] != 'evaluate' or arm_req['runId'] != req['runId'] or
                arm_req['session'] != session or arm_res != {'ok': True, 'data': {'value': {'count': 1}}} or
                not start - 5 <= arm_response.stat().st_mtime <= start or
                'button.J_batchEditProduct' not in arm_code or match[1] not in arm_code or
                "setAttribute('data-codex-miao-batch'" not in arm_code):
            refuse()
        # The durable interval must contain just network observation and this
        # rejected click. Any second action, missing round, or transport gap fails.
        actions = []
        for candidate in root.glob('*.json'):
            if candidate.name.endswith('.result.json') or not re.fullmatch('[0-9a-f]{32}.json', candidate.name):
                continue
            if not start <= candidate.stat().st_mtime <= end:
                continue
            item = json.loads(candidate.read_text(encoding='utf-8'))
            if item.get('runId') != req['runId']:
                refuse()
            if candidate == request:
                actions.append('rejected_click')
            elif item.get('action') == 'network' and (item.get('args') or {}).get('cmd') in ('list', 'start'):
                reply = json.loads(candidate.with_name(candidate.stem + '.result.json').read_text(encoding='utf-8'))
                if reply.get('ok') is not True:
                    refuse()
                actions.append(item['args']['cmd'])
            else:
                refuse()
        if sorted(actions) != ['list', 'rejected_click', 'start']:
            refuse()
        return {'runtime_sha256': digest, 'round_id': token, 'arm_round_id': arm_token,
                'request_sha256': trace['request_sha256'], 'result_sha256': trace['result_sha256'],
                'input_dispatched': False, 'run_id': req['runId']}
    except (KeyError, TypeError, ValueError, OSError):
        refuse()
