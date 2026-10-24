# 妙手编辑器：已观察的入口与读取方法

证据日期：2026-10-24/25。先只读观察，后在用户指定商品上完成 5 张主图、4 张详情替换、不同标题写入、单次保存及双端读回。以下是现场锚点，不是永久选择器契约；每次先 snapshot，优先使用本次返回的元素引用，不能复用文档中或其他任务的 `@e…`。

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

标题填入后等待真实值稳定；快照引用可能出现 `focused` 属性，标题组会新增“恢复”按钮和更新字数。核查非目标数据时区分这些 UI 状态与实际字段变化，不因首次快照或正则漏掉带焦点的标题框而重新填写。

SKU/价格库存是独立页签；其未显示不代表保存不涉及它。基线要有 SKU ID/规格、价格、库存及观察覆盖情况；只有读取到全部 SKU 时才声称全量比对。

实测 24 个规格最初只挂载 20 行。滚动 `.sku-info.tab-content` 并等待渲染后可读齐；后台页持续不更新时可按桥接协议临时开启 `Emulation.setFocusEmulationEnabled`，结束后关闭，不用再次 `Page.bringToFront` 切走用户焦点。现价列是 `.price-col`，来源价是 `.sourcePrice-col`；库存同样区分 `.stock-col` 与 `.sourceStock-col`。顶部 `.hidden-input` 不是 SKU 搜索框。读取时逐行取规格、现价、现货库存、商家编码、条形码和状态；对应关系现场确认。

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

链接导入实测会先把输入 URL 临时显示在槽位，再由页面实际 `POST /api/v2/move/batch/uploadImage` 返回 `result=success`、`successUrls` 后换成正式素材地址。不能一看到 src 改了就记上传完成；保存对应响应、最终槽位与素材内容。导入会重编码并生成不同素材标识，不要求正式地址等于输入地址。

本地文件上传实测先得到妙手 `tmp_upload` 地址，上传窗口可能自动关闭。本次先把临时文件与本地 SHA256 核对，再重开同一槽位替换窗口，将已上传的临时 URL 通过图片链接导入为正式素材，等待成功响应及最终槽位一致；PNG 正式图与本地像素一致。其他任务按实际返回判断，不把临时 src 当正式素材，也不因窗口关闭重传文件。若使用临时 DOM 标记，每次打开槽位前清掉本任务旧标记，要求目标及文件 input 各唯一；残留标记会让 CSS 命中前一个槽位。

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

采用白名单保存图文及需保护字段，不保留无关联系方式、用户标识或完整响应。没有此请求时退回 DOM，并明确缺口。

## 已验证的保存结果

本次点击可见“保存到抖店(F)”一次，观察到页面 `POST /api/v2/product/product/saveEditProductInfo`，响应 `{"result":"success"}`。请求的 `productInfo` 包含字符串 `productId`、`cateId`、`pics`、`mainImageThreeToFour`、`specPic`、`whiteBgImgUrl`、`description`、`changeFields`；本次 `changeFields` 仅 `mainImg`、`descImg`。此为图片修改的现场证据，不代表其他操作的载荷契约，也不用于直接重放写接口。

2026-10-25 不同标题与图片一起修改时，实际载荷增加 `title`，`changeFields` 为 `base`、`mainImg`、`descImg`。`base` 同时发送基础属性、运费、重量、限购、售后等字段；并非只传一条标题。保存前后的完整字段比对不可省。本次新标题、5+4 个 `png_m_...` 正式素材逐槽读回匹配，24 个 SKU 与保护字段一致，保持下架，未载入草稿、未见驳回；消费者展示和最终审核仍单独判断。

保存后从新开的妙手页读取实际 `getProductBaseEditInfo` 响应，并从新开的官方编辑页独立核对：5+4 张目标素材逐槽匹配、24 个 SKU 与保护字段保持、未加载草稿、未见驳回、保持原下架状态。官方 CDN 的 obj/img、域名和转换参数可能不同；本次结合上传响应按 `jpeg_m_<素材标识>` 对应，不能推广成无条件删 URL 参数。

本次后台页曾出现上传弹窗和“上传中”遮罩残留，点击关闭后仍显示；全局 Escape 实际关闭了商品编辑窗口并丢失未保存输入。不要用 Escape 盲关图片弹窗。遇到类似情况先用实际上传响应和最终槽位判定状态，再按恢复参考处理；不要因遮罩残留重复上传或保存。

## 教程来源

- [教程总目录](https://v1o7zyazq9.feishu.cn/wiki/OpquwOPHeiAeAFkPFcCcqHoonYc)
- [批量修改](https://v1o7zyazq9.feishu.cn/wiki/JevdwxYxVi14FKk0epTcxX64nHb)
- [AI功能集合](https://v1o7zyazq9.feishu.cn/wiki/EMaNwMSUkiRl0EkTQKJcRcbJnc7)

教程描述的是产品能力，不是当前账号所有权益，也不是本 skill 的实测验收记录。软件复制额度、AI积分、套餐及独立分销工具分别核对。
