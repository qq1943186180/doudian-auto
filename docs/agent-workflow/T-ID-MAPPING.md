# T-ID ↔ Linear 映射

| T-ID | Linear | 状态 | 说明 |
|---|---|---|---|
| T-20261025-001 | [194-67](https://linear.app/1943186180/issue/194-67) | done | 妙手更换新版5主图+4详情及不同标题，单次保存成功、双端新页读回一致；24SKU及商业字段保留、原下架不变；编辑中电脑重启在原任务核验续办；补base连带字段和唯一槽位标记指导 |
| T-20261024-002 | [194-66](https://linear.app/1943186180/issue/194-66) | done | 用户指定商品经妙手替换5主图+4详情，UI单次保存success、新页妙手/抖店双端读回匹配；24 SKU和商业字段保持、原下架不变；复用现有素材，无新增生图费；补实测流程与未保存窗口丢失恢复经验 |
| T-20261024-001 | [194-65](https://linear.app/1943186180/issue/194-65) | done | 创建并安装miaoshou-product-workflow；4文件校验及安装哈希一致，覆盖图文编辑、字段保护、提交未知核查与抖店读回；真实保存尚未验收，未改线上商品（实现eeef97f） |
| T-20261022-013 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 商品 3848316916011762046 全量改版：标题 59/60 units（零错误）、5 主图 + 4 详情全部 ImageGen 独立生成（中文由模型直出，不用 Pillow 排版）、已发布 saved/accepted/pending；顺带修两个误报 bug——基线只取 open 首帧（改连续两次一致才落盘）、价格库存虚拟列表行数差异被当作保留字段变化（opt-in 子多重集容忍＋记录覆盖范围）（commit 2ab9fa7） |
| T-20261022-012 | [194-54](https://linear.app/1943186180/issue/194-54) | done | Codex 五轮终审：「没有新问题，title-only 生命周期代码修复完成，B 解锁」；他探针验证重复发布攻击不成立；补 landed=True 零覆盖（传输异常但已落地的端到端：submitting/unknown→resume 拒→verify 读回→saved）。B＝下次确需改不同标题的授权任务 dry-run→apply→verify 一次（commit 991d13d） |
| T-20261022-011 | [194-54](https://linear.app/1943186180/issue/194-54) | done | Codex 四轮复核：三项旧洞关闭、无新 P0/P1；修新 P2——`rejected/unknown`（提交超时后 verify 读回驳回）原来无出口导致商品永久阻塞，现为带 readback 证据的结案（保留 unknown 不伪造 accepted）；顺带修假 editor 两处失真（validation_failed 误更新服务端、fresh 未重建页面）与锁测试偏弱（commit 0085751） |
| T-20261022-010 | [194-54](https://linear.app/1943186180/issue/194-54) | done | Codex 三轮复核（内存探针复现）：修 abandon 无锁竞态（改 browser.lock→job.lock 内重读）、resume 目标已满足仍发布（改只读出口 title_already_current，noop 保持 noop）、abandon 黑名单 fail open（改白名单＋提交状态组合校验＋空白原因拒绝）；假 editor 改服务端/页面分离（commit 638f4c4） |
| T-20261022-009 | [194-54](https://linear.app/1943186180/issue/194-54) | done | D1–D5：title apply 补成完整生命周期——独立新页基线、草稿/驳回先停、noop 收窄、图片分项、validation_failed 阻塞侧；新增 `title resume`（复用原 manifest/before，submitting 起禁 resume）与 `title abandon`（可审计退出，不碰线上）；规格豁免改为每不同规格值一次（commit f922393） |
| T-20261022-008 | [194-54](https://linear.app/1943186180/issue/194-54) | done | Codex 二轮复核：堵上新引入的 P1（title job 可进通用 upload 并先删图），两层拒绝；扫描器改安全阶段白名单＋按目录枚举＋要求 JSON 对象（commit 935e34b） |
| T-20261022-007 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 按 Codex 评审修 `title apply` 四个 P1（锁内重查兄弟任务、title job 加载/核验闭环、protected 与最终标题闸门、写页面期间落 editing）＋ 三个 P2；补临时脚本操作的追溯记录；修规格豁免漏报 |
| T-20261022-006 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 商品 3848316916011762046 标题改版（神器+套装问题、补磁吸/不锈钢/2-3件套），已提交等审核；新增 `title apply` 只改标题路径；修夸大词漏报与规格变体误报（commit 5a8ef1d） |
| T-20261022-005 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 新增 `title check/diagnose` 离线校验（不生成标题）；修正长度下限 15→16（平台 8-30 汉字即 16-60 字符）；新增跨任务提交保护；同步 skill 文档（commit 4ef2645） |
| T-20261022-004 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 按用户授权改类目为「家装建材 > 隔音保温 > 隔音材料」并重新提交成功；verify=saved/pending，驳回标记消失（commit d1c3590）；另修 CDN host 误报与 review_status 残留 |
| T-20261022-003 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 全链路首测：upload 走通、submit 被平台以「类目不符」驳回；修 section 下标错位 + 发布结果分类 + 草稿假阳性（commit e44bf5c） |
| T-20261022-001 | [194-54](https://linear.app/1943186180/issue/194-54) | done | WorkBuddy接手第二轮：详情图读取改为实时预览面板，真实验证通过（commit f77620d，已并入 e44bf5c） |
| T-20261021-004 | [194-54](https://linear.app/1943186180/issue/194-54) | todo | 用户指定WorkBuddy接手；实现及离线验证已完成，真实连接/试传验收待办 |
