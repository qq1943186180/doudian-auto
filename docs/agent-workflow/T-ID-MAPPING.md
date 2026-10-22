# T-ID ↔ Linear 映射

| T-ID | Linear | 状态 | 说明 |
|---|---|---|---|
| T-20261022-004 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 按用户授权改类目为「家装建材 > 隔音保温 > 隔音材料」并重新提交成功；verify=saved/pending，驳回标记消失（commit d1c3590）；另修 CDN host 误报与 review_status 残留 |
| T-20261022-003 | [194-54](https://linear.app/1943186180/issue/194-54) | done | 全链路首测：upload 走通、submit 被平台以「类目不符」驳回；修 section 下标错位 + 发布结果分类 + 草稿假阳性（commit e44bf5c） |
| T-20261022-001 | [194-54](https://linear.app/1943186180/issue/194-54) | done | WorkBuddy接手第二轮：详情图读取改为实时预览面板，真实验证通过（commit f77620d，已并入 e44bf5c） |
| T-20261021-004 | [194-54](https://linear.app/1943186180/issue/194-54) | todo | 用户指定WorkBuddy接手；实现及离线验证已完成，真实连接/试传验收待办 |
