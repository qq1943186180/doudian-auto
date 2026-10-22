# T-ID ↔ Linear 映射

| T-ID | Linear | 状态 | 说明 |
|---|---|---|---|
| T-20261022-008 | [194-54](https://linear.app/1943186180/issue/194-54) | done | Codex 二轮复核：堵上新引入的 P1（title job 可进通用 upload 并先删图），两层拒绝；扫描器改安全阶段白名单＋按目录枚举＋要求 JSON 对象（commit 935e34b） |
| T-20261022-007 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 按 Codex 评审修 `title apply` 四个 P1（锁内重查兄弟任务、title job 加载/核验闭环、protected 与最终标题闸门、写页面期间落 editing）＋ 三个 P2；补临时脚本操作的追溯记录；修规格豁免漏报 |
| T-20261022-006 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 商品 3848316916011762046 标题改版（神器+套装问题、补磁吸/不锈钢/2-3件套），已提交等审核；新增 `title apply` 只改标题路径；修夸大词漏报与规格变体误报（commit 5a8ef1d） |
| T-20261022-005 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 新增 `title check/diagnose` 离线校验（不生成标题）；修正长度下限 15→16（平台 8-30 汉字即 16-60 字符）；新增跨任务提交保护；同步 skill 文档（commit 4ef2645） |
| T-20261022-004 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 按用户授权改类目为「家装建材 > 隔音保温 > 隔音材料」并重新提交成功；verify=saved/pending，驳回标记消失（commit d1c3590）；另修 CDN host 误报与 review_status 残留 |
| T-20261022-003 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 全链路首测：upload 走通、submit 被平台以「类目不符」驳回；修 section 下标错位 + 发布结果分类 + 草稿假阳性（commit e44bf5c） |
| T-20261022-001 | [194-54](https://linear.app/1943186180/issue/194-54) | done | WorkBuddy接手第二轮：详情图读取改为实时预览面板，真实验证通过（commit f77620d，已并入 e44bf5c） |
| T-20261021-004 | [194-54](https://linear.app/1943186180/issue/194-54) | todo | 用户指定WorkBuddy接手；实现及离线验证已完成，真实连接/试传验收待办 |
