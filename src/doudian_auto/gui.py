import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from .bridge import Bridge
from .editor import Editor
from .errors import DoudianError
from .jobs import DATA_ROOT, load_job, prepare, read_json
from .batch import batch_status, create_batch, recover_expired_claims
from .workflow import Workflow


def launch(endpoint='http://127.0.0.1:10086', smoke_test=False):
    root = tk.Tk()
    if smoke_test:
        root.withdraw()
    root.title('抖店本地上传')
    root.geometry('860x690')
    root.minsize(760,600)
    panel = ttk.Frame(root,padding=18)
    panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='抖店商品上传',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    ttk.Label(panel,text='选择已做好的图片 → 准备任务 → 上传预览 → 发布并核验').pack(anchor='w',pady=(6,12))
    fields = {}
    for key,label in [('shop','店铺名称'),('url','现有商品编辑链接'),('title','新标题'),('assets','素材文件夹'),('job','任务文件夹')]:
        row = ttk.Frame(panel)
        row.pack(fill='x',pady=4)
        ttk.Label(row,text=label,width=18).pack(side='left')
        fields[key] = tk.StringVar()
        ttk.Entry(row,textvariable=fields[key]).pack(side='left',fill='x',expand=True)
        if key in ('assets','job'):
            def choose(k=key):
                value = filedialog.askdirectory(parent=root,title='选择文件夹')
                if value:
                    fields[k].set(value)
                    if k == 'job':
                        try:
                            manifest = load_job(value)
                            for name in ('shop','title'):
                                fields[name].set(manifest[name])
                            fields['url'].set(manifest['edit_url'])
                        except (DoudianError,OSError,ValueError,KeyError):
                            status.set('任务文件夹无效，请检查。')
            ttk.Button(row,text='选择',command=choose).pack(side='right',padx=(6,0))
    ttk.Label(panel,text='主图命名 main_01～05；详情 detail_01 起。只改标题、方主图和标准详情。').pack(anchor='w',pady=(10,4))
    status = tk.StringVar(value='可离线准备任务。浏览器连接后才能上传。')
    ttk.Label(panel,textvariable=status,wraplength=800).pack(anchor='w',pady=6)
    actions = ttk.Frame(panel)
    actions.pack(fill='x',pady=6)
    log = tk.Text(panel,height=16,wrap='word',font=('Microsoft YaHei UI',10))
    log.pack(fill='both',expand=True,pady=(8,0))
    batch_panel = ttk.LabelFrame(panel, text='全仓优化批次', padding=8)
    batch_panel.pack(fill='x', pady=(10, 0))
    batch_summary = tk.StringVar(value='尚未选择批次。')
    ttk.Label(batch_panel, textvariable=batch_summary).pack(anchor='w')
    batch_log = tk.Text(batch_panel, height=5, wrap='word', font=('Microsoft YaHei UI', 9))
    batch_log.pack(fill='x', pady=(4, 4))
    batch_buttons = ttk.Frame(batch_panel)
    batch_buttons.pack(fill='x')
    batch_busy = False
    messages = queue.Queue()
    buttons = []
    busy = False

    def close():
        if busy:
            status.set('正在操作商品，请等当前步骤结束后再关闭。')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)

    def start(action):
        nonlocal busy
        if busy:
            return
        values = {key:value.get().strip() for key,value in fields.items()}
        busy = True
        for button in buttons:
            button.configure(state='disabled')
        status.set('处理中，请保留商品编辑页…')

        def work():
            try:
                if action == 'prepare':
                    result = prepare(values['assets'],values['title'],values['url'],values['shop'])
                elif action == 'doctor':
                    connection = Bridge(endpoint).status()
                    result = {'browser_ready':bool(connection.get('running') and connection.get('extension_connected') and not connection.get('version_mismatch')), 'connection':connection}
                else:
                    flow = Workflow(values['job'],Editor(Bridge(endpoint)))
                    result = flow.verify() if action == 'verify' else getattr(flow,action)(apply=True)
                messages.put((True,action,result))
            except (DoudianError,OSError,ValueError,KeyError,TypeError) as exc:
                message = str(exc) if isinstance(exc,DoudianError) else f'本地文件或任务异常：{type(exc).__name__}'
                messages.put((False,action,{'message':message}))
        threading.Thread(target=work,daemon=True).start()

    def batch_action(action):
        nonlocal batch_busy
        if batch_busy:
            return
        input_path = None
        if action == 'create':
            input_path = filedialog.askopenfilename(parent=root, title='选择商品清单',
                                                    filetypes=[('JSON', '*.json')])
            if not input_path:
                return
            default_shop = simpledialog.askstring('店铺', '清单缺少店铺名时使用此店铺：', parent=root)
            if default_shop is None:
                return
        batch_busy = True
        for button in batch_action_buttons:
            button.configure(state='disabled')

        def work_batch():
            try:
                if action == 'resume':
                    result = recover_expired_claims()
                elif action == 'create':
                    result = create_batch(input_path, shop=default_shop.strip() or None)
                else:
                    result = batch_status()
                messages.put((True, 'batch_' + action, result))
            except (DoudianError, OSError, ValueError, KeyError, TypeError) as exc:
                message = str(exc) if isinstance(exc, DoudianError) else f'批次队列异常：{type(exc).__name__}'
                messages.put((False, 'batch_' + action, {'message': message}))
        threading.Thread(target=work_batch, daemon=True).start()

    batch_action_buttons = []
    for label, action in [('导入清单建批次', 'create'), ('刷新批次状态', 'status'), ('续办过期素材任务', 'resume')]:
        button = ttk.Button(batch_buttons, text=label, command=lambda a=action: batch_action(a))
        button.pack(side='left', padx=(0, 8))
        batch_action_buttons.append(button)

    for label,action in [('检查连接','doctor'),('1 准备任务','prepare'),('2 上传预览','upload'),('3 发布并核验','submit'),('重新核验','verify')]:
        button = ttk.Button(actions,text=label,command=lambda a=action:start(a))
        button.pack(side='left',padx=(0,8))
        buttons.append(button)

    def poll():
        nonlocal busy, batch_busy
        try:
            ok,action,result = messages.get_nowait()
            if action.startswith('batch_'):
                batch_busy = False
                for button in batch_action_buttons:
                    button.configure(state='normal')
                if ok:
                    if action == 'batch_create':
                        batch_summary.set(f"已创建批次 {result['batch_id']}，共 {result['count']} 件，"
                                          f"隔离 {result.get('blocked', 0)} 件。")
                        batch_log.delete('1.0', 'end')
                        root.after(150, poll)
                        return
                    data = result.get('status', result)
                    counts = data.get('counts', {})
                    batch_summary.set('批次计数：' + json.dumps(counts, ensure_ascii=False) +
                                      ('；本次续办释放过期领取 ' + str(result.get('recovered_agent_leases', 0)) + ' 件。'
                                       if action == 'batch_resume' else ''))
                    batch_log.delete('1.0', 'end')
                    if data.get('phase_timing'):
                        batch_log.insert('end', '阶段耗时（秒，平均）：' + json.dumps(
                            data['phase_timing'], ensure_ascii=False) + '\n')
                    for item in data.get('products', []):
                        batch_log.insert('end', f"{item['product_id']}  {item['state']}  "
                                         f"提交:{item['submission_state']}  {item.get('last_error') or ''}\n")
                else:
                    batch_summary.set(result['message'])
                root.after(150, poll)
                return
            busy = False
            for button in buttons:
                button.configure(state='normal')
            if ok and action == 'prepare':
                fields['job'].set(result['job_dir'])
            labels = {'prepare':'素材校验通过，任务已准备。','upload':'已上传预览，尚未发布。','submit':'已发布并重开核验。','verify':'已重开核验。'}
            status.set((('连接正常。' if result.get('browser_ready') else '扩展未连接；可继续离线准备。') if action == 'doctor' else labels.get(action,'完成。')) if ok else result['message'])
            # Keep GUI readable; full evidence is stored inside the task folder.
            summary = {k:v for k,v in result.items() if k not in ('manifest',)}
            log.insert('end',json.dumps(summary,ensure_ascii=False,indent=2)+'\n\n')
            log.see('end')
        except queue.Empty:
            pass
        root.after(150,poll)
    poll()
    if smoke_test:
        root.update_idletasks()
        if len(fields) != 5 or len(buttons) != 5:
            raise RuntimeError('GUI controls incomplete')
        root.after(100,root.destroy)
    root.mainloop()
