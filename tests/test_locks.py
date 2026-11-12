"""锁的失效模式回归。

两个真实故障驱动这些用例：

1. 锁文件残留会让后面每一次运行都报 busy，而残留的成因是删除锁文件的动作被外部
   删除守卫拦下（守卫抛的是 SystemExit，不是普通异常，整个流程会被打断）。
2. 被杀死的进程留下的死锁必须能自己恢复，不能每次都要人工 unlock。
"""

import json
import os
from pathlib import Path

import pytest

from doudian_auto.bridge import Bridge
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import Lock, TransportLock


def test_dead_lock_is_reclaimed_but_live_lock_is_never_stolen(tmp_path, monkeypatch):
    path = tmp_path / 'browser.lock'
    path.write_text('4242', encoding='ascii')
    monkeypatch.setattr('doudian_auto.jobs.process_alive', lambda pid: False)
    with Lock(path) as held:
        assert path.read_text(encoding='ascii') == str(os.getpid())
    assert not path.exists()

    path.write_text('4242', encoding='ascii')
    monkeypatch.setattr('doudian_auto.jobs.process_alive', lambda pid: True)
    with pytest.raises(DoudianError) as caught:
        with Lock(path):
            pass
    assert caught.value.code == 'busy'
    assert path.read_text(encoding='ascii') == '4242'


def test_unreadable_lock_content_is_refused_not_deleted(tmp_path):
    path = tmp_path / 'browser.lock'
    path.write_text('not-a-pid', encoding='ascii')
    with pytest.raises(DoudianError) as caught:
        with Lock(path):
            pass
    assert caught.value.code == 'invalid_lock'
    assert path.exists()


def test_blocked_release_does_not_break_the_run_and_next_run_recovers(tmp_path, monkeypatch):
    """释放锁的删除被拦下时，不能把整条流程打断；下一次运行按死锁回收。"""
    import os
    path = tmp_path / 'browser.lock'
    original = Path.unlink

    def blocked(self, *args, **kwargs):
        raise SystemExit(1)

    monkeypatch.setattr(Path, 'unlink', blocked)
    with Lock(path):
        pass
    # SystemExit 必须被吞掉：调用方看到的是正常退出。
    assert path.exists()

    monkeypatch.setattr(Path, 'unlink', original)
    monkeypatch.setattr('doudian_auto.jobs.process_alive', lambda pid: False)
    with Lock(path):
        assert path.read_text(encoding='ascii') == str(os.getpid())
    assert not path.exists()


def test_transport_lock_is_exclusive_and_released_without_deleting_anything(tmp_path, monkeypatch):
    path = tmp_path / 'transport.lock'
    deleted = []
    original = Path.unlink
    monkeypatch.setattr(Path, 'unlink', lambda self, *a, **k: (deleted.append(str(self)), original(self, *a, **k))[1])
    with TransportLock(path):
        with pytest.raises(DoudianError) as caught:
            with TransportLock(path):
                pass
        assert caught.value.code == 'busy'
    # 释放后可以再次取得，且整个过程不删除任何文件。
    with TransportLock(path):
        pass
    assert deleted == []
    assert path.exists()


def test_repeated_browser_commands_delete_no_files(tmp_path, monkeypatch):
    """每条浏览器命令都不删除文件：删除既磨损磁盘，也会被外部守卫拦下。"""
    monkeypatch.setattr('doudian_auto.ego_bridge.DATA_ROOT', tmp_path)
    monkeypatch.setattr('doudian_auto.ego_bridge.shutil.which', lambda name: 'ego-browser.cmd')

    def run(command, **kwargs):
        request = max((p for p in tmp_path.rglob('*.json') if len(p.stem) == 32),
                      key=lambda p: p.stat().st_mtime_ns)
        request.with_name(request.stem + '.result.json').write_text(
            json.dumps({'ok': True, 'data': {'seen': True}}), encoding='utf-8')

    monkeypatch.setattr('doudian_auto.ego_bridge.subprocess.run', run)
    deleted = []
    original = Path.unlink
    monkeypatch.setattr(Path, 'unlink',
                        lambda self, *a, **k: (deleted.append(str(self)), original(self, *a, **k))[1])
    bridge = Bridge('ego')
    for _ in range(5):
        assert bridge.command('snapshot') == {'seen': True}
    assert deleted == []
    # 待核查标记保留在盘上，下一条命令直接覆盖，不会删除。
    assert (bridge.session_dir / 'pending-command.json').is_file()
