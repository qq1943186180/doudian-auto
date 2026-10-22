# 抖店本地上传

入口：先读 HANDOFF.md，再查看 git status --porcelain。
本项目只操作中国抖店现有商品。真实浏览器联调已于 2026-10-22 在商品 3784643089604411407 上完成一次（`prepare → upload → submit → verify`，`stage=saved`，含一次改类目后重新提交）；这只能证明该商品该路径可用，不得据此把其他商品或类目的离线模拟记为线上验证，也不得把「已提交」记成「消费者端已生效」。
默认写入范围仅标题、方主图和标准详情。保留商业字段，提交超时后先verify，禁止自动重复发布。
不提交本机任务、图片、浏览器数据或登录凭据。Python测试用 .venv/Scripts/python.exe -m pytest -q；DOM适配测试用 npm test。
