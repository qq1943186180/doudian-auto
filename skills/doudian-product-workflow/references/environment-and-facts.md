# 环境、事实文件与本地检查

## 定位和降级

这是本机 Windows / PowerShell 工作流，不把其安装脚本描述为跨平台工具。先 `Get-Command doudian-auto`，检查返回的启动器定位真实项目；恢复路径以项目 HANDOFF 和 `git rev-parse --show-toplevel` 为准，不假定 `~/code/clis/doudian-auto` 仍存在。

下例的 `$repo` 是实际源码仓库根目录，`$skill` 是已安装的本技能目录或 `<repo>/skills/doudian-product-workflow`，执行前替换占位值：

```powershell
$repo = '<实际仓库根目录>'
$skill = '<本技能实际目录>'
$projectPython = Join-Path $repo '.venv/Scripts/python.exe'
& $projectPython -c 'import doudian_auto, PIL; print(doudian_auto.__file__)'
& $projectPython (Join-Path $skill 'scripts/doudian_check.py') assets '<素材目录>' --title '<标题>' --out '<检查.json>'
# 仅用于旧版手工 sections 快照；CLI read 的 protected 快照按原 CLI 任务 verify 核验
& $projectPython (Join-Path $skill 'scripts/doudian_check.py') compare '<旧sections快照.json>' '<新sections快照.json>' --title '<标题>' --details 4 --out '<比较.json>'
```

必须使用能导入本项目 `doudian_auto` 和 Pillow 的解释器；不能用不明版本的裸 `python`。缺依赖时先完成文案与素材清单并报告阻塞；不使用旧规则副本宣称校验通过。需要安装时使用**仓库根** `scripts/install-local.ps1`；**技能目录** `scripts/doudian_check.py` 是不同文件。

脚本 `assets` 要求五张不重复方主图，命名 `main_01_*.jpg` 到 `main_05_*.jpg`，详情以 `detail_` 开头；接受的实际扩展名为 jpg/jpeg/png。局部替换不套用整套数量规则。`compare` 只比较旧 `sections` 快照实际采到的内容；CLI 的 `protected` 格式另由程序核验。

直接抖店适配器使用 Kimi WebBridge 登录态，端点优先级 `--endpoint` > `DOUDIAN_BRIDGE_URL` > `http://127.0.0.1:10086`。先读当前可用的 `kimi-webbridge` 操作协议，`doctor` 失败再读可用的 `kimi-webbridge-boot`；从当前技能清单定位文件，不写死 WorkBuddy 路径。缺少桥接/浏览器时可离线 prepare，不执行 upload/submit。服务修复涉及 stop/restart/upgrade 时确认其在现有授权内；不自动重放写请求、不导出 Cookie。

## facts JSON

`title diagnose --facts` / `title apply --facts` 读取 UTF-8 JSON 对象。字段均可省略，省略表示未确认，不表示可以猜值。商品 ID 一律字符串。

```json
{
  "product_id": "<目标商品字符串ID>",
  "category": "<当前真实类目>",
  "confirmed": {
    "brand": "<已确认品牌>",
    "material": ["<已确认材质>"],
    "scene": ["<有依据的场景>"],
    "attributes": ["<已确认属性>"],
    "specs": {"<规格名>": ["<真实SKU规格值>"]}
  },
  "unconfirmed": ["<尚无证据的宣传词>"]
}
```

占位符需替换或删除。事实来源另存证据记录，包含字段、来源文件/页面及时间；`TitleFacts` 本身不校验来源，不把旧标题或图片中的宣传当成认证。`brand/category` 是诊断资料，不授权变更店铺对应字段。

当前本地 `title.py` 规则为 16–60 单位：CJK/全宽按 2，其余按 1，emoji/组合符可能与平台计数不同。`check` 只验证长度、空白、控制字符；`diagnose` 的语义提示须结合事实处理。规则变更以当前代码及页面为准，本地通过不代表平台接受。

## 可选免费课程检索

`GET http://127.0.0.1:5001/api/rag/search`，参数 `q`、`limit`、`platform`、`market`、`source_type`。`q` 必填；筛选值按服务支持值填写，不猜枚举。最小请求：

```powershell
$courseQuery = [uri]::EscapeDataString('<真实商品关键词与待解决问题>')
Invoke-RestMethod -Uri "http://127.0.0.1:5001/api/rag/search?q=$courseQuery&limit=5" -TimeoutSec 5
```

失败最多重试一次，然后用已确认商品资料继续并记录未取得课程参考；服务不可用不阻塞主流程。其他平台或 `general_fallback` 结果只作适用的方法参考。默认不调用收费 `/api/rag/ask`。
