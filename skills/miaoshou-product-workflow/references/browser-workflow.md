# 妙手编辑器：已观察的入口与读取方法

证据日期：2026-10-24。使用本机已登录 Edge 只读检查，未上传测试文件、未保存商品。以下是现场锚点，不是永久选择器契约；每次先 snapshot，优先使用本次返回的元素引用，不能复用文档中或其他任务的 `@e…`。

## 连接与商品定位

读取 `kimi-webbridge/SKILL.md` 后使用其 `/command` 协议。Windows 每条请求写入独立 UTF-8 无 BOM 文件再由 `curl.exe --data-binary @文件` 发送，返回后清理。session 放顶层；地址以服务 status 为准。

先 `list_browser_tabs` 看已有页。只读查看可 `attach_tab`，建立编辑基线则新开快速编辑页，防止复用他人的脏输入。首次新建组名可用“妙手商品编辑”，同一任务沿用同一 session。

```json
{"action":"navigate","args":{"url":"https://v2-dd.chengji-inc.com/product/quick_edit","newTab":true,"group_title":"妙手商品编辑"},"session":"当前任务的固定session"}
```

快速编辑页先读页头店铺，再用“商品ID”筛选框和“查询”。所有商品 ID 以字符串处理，避免 JavaScript Number 对长 ID 丢精度。查询后等待列表结果，再检查目标 ID 所在行；不能把加载中的 `共0条` 当最终结果。

“编辑商品”打开妙手大弹窗；同一行“抖店编辑”进入官方后台。大弹窗包括左侧商品列表、内容页签、“保存到抖店(F)”、“上一个”、“下一个”、“关闭”。左右列表和页签会独立重渲染，切换后重新核对当前商品身份。

## 标题与商业字段

“商品信息”页签里主标题、导购短标题、参考价、运费模板、商品限购、售后、属性同屏存在。“请输入”并不唯一；按“商品标题”标签及表单分组定位，读当前 value 后再填。

SKU/价格库存是独立页签；其未显示不代表保存不涉及它。基线要有 SKU ID/规格、价格、库存及观察覆盖情况；只有读取到全部 SKU 时才声称全量比对。

有“AI推荐”“属性判准”“AI一键填写”等控件，现有商品可能带勾选。只读记录不改变这些开关，也不据此假定保存只会发送已改字段。

## 主图逐槽替换

“主图”页签下同时有商品主图、3:4 主图、规格图、白底图、详情图多个图片组。按组名和容器定位，不在整个 document 搜索第 n 个“删除/替换”。

已观察到方图操作元素的 class：

```text
.J_editProductReplaceGroup  替换
.J_editProductAiReplaceGroup AI换图
.J_editProductDelete        删除
.J_editProductCutout        抠图
```

这些动作不一定有可访问性引用。若需要 CSS/JS，先观察当前目标组的 DOM、目标槽位图片及祖先容器，再限定到该槽位；全局 `.J_editProductReplaceGroup` 只会命中第一项，不能用于任意槽位替换。

普通“替换”打开“上传/替换图片”窗口；“AI换图”是另一条会涉及生成和额度的路径。替换窗口可从本地、链接、来源1688图、现有主图/SKU/详情图或图库选取。不要因来源标签中已有图片就用上家的变体图替代当前 SKU。

界面明确说明：3:4 图受接口限制不能全部删除，需要去商家后台。这个限制只适用于该格式，不能推断方图也一样，也不能为了绕过限制转到其他格式操作。

## 详情与本地上传

“详情图”独立页签有“上传图片”“全选”“批量删除”等按钮。

“上传图片”先打开“上传/替换图片”弹窗，弹窗内还有一个“上传图片”按钮和最终“确定”。必须区分图片选择器的确认与商品保存。

实测 DOM 存在标准多文件 input：

```html
<input class="el-upload__input" name="file" multiple accept=".jpg, .jpeg, .bmp, .png, .gif, .webp" type="file">
```

需以实际上传弹窗及当前 DOM 确认 input 归属，再按桥接 `upload` 工具传本地绝对路径；input 可能在弹窗打开前后挂载变化，不硬编码“页面唯一一个 input”。同一控件支持的格式和显示文案可能不同，按两者交集及平台限制准备文件。

详情上传弹窗当时提示 jpg/jpeg/png、单图尺寸及体积上限，并显示按剩余容量计算的可选张数。**这些限制和剩余数每次读当前页面**，不把一次剩余36张当永久上限。

详情缩略图曾显示 `0 x 0`，仍有14张图片条目；这是尺寸观测未完成，不能据此判空。上传后核对远端图片、条目数和顺序，不依赖尺寸提示单一信号。

## 结构化读取：仅使用页面已经发出的请求

可以在当前任务的新页、打开目标商品之前 `network start`，观察页面自己的请求，用 `network list` 查找并在 stop 前 `network detail` 读取。不要输出/保存整份请求头：其中可能含登录信息。只保存需要的响应字段及来源元数据，完成后 stop。

2026-10-24 观察到：

```text
POST /api/v2/product/product/getProductBaseEditInfo
页面请求体包含 productId=<字符串ID>&isDraft=0
响应顶层：result, productId, productInfo, categoryId, brandName
```

`body` 可能已是对象或 JSON 字符串；`productInfo` 同样先检查类型再解析，不对对象重复 JSON.parse。核对响应成功、商品 ID、来源标签、时间与当前店铺一致；`isDraft=0` 是当时的读取参数，不能单凭它保证没有审核版本或缓存。

观察到的相关字段：`name`、`img`、`pic`、`description`、`descriptionImgList`、`specs`、`specPrices`、`specPics`、`mainPic34`、`whiteBackGroundPicUrl`、`freightId`、`afterSaleService`、`afterSaleServiceV2`、`cid`、`brandId`、`productAuditInfo`、`draftStatus`。**字段名不能替代语义验证**：图片数组/字符串、价格单位、SKU标识、空值与其他字段的对应关系须对照当前 DOM/原商品，不能凭名字假设后直接写入或归一化。

采用白名单保存图文及需保护字段，不保留无关联系方式、用户标识或完整响应。没有此请求时退回 DOM，并明确缺口。现有证据没有确定妙手保存接口、提交载荷、任务轮询或错误码契约；通过可见保存按钮操作，不猜写接口或拿读接口成功冒充写入成功。

## 教程来源

- [教程总目录](https://v1o7zyazq9.feishu.cn/wiki/OpquwOPHeiAeAFkPFcCcqHoonYc)
- [批量修改](https://v1o7zyazq9.feishu.cn/wiki/JevdwxYxVi14FKk0epTcxX64nHb)
- [AI功能集合](https://v1o7zyazq9.feishu.cn/wiki/EMaNwMSUkiRl0EkTQKJcRcbJnc7)

教程描述的是产品能力，不是当前账号所有权益，也不是本 skill 的实测验收记录。软件复制额度、AI积分、套餐及独立分销工具分别核对。
