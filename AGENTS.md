# 抖店本地上传

入口：先读 HANDOFF.md，再查看 git status --porcelain。
本项目只操作中国抖店现有商品。真实浏览器联调尚未完成；不得把离线模拟记为线上验证。
默认写入范围仅标题、方主图和标准详情。保留商业字段，提交超时后先verify，禁止自动重复发布。
不提交本机任务、图片、浏览器数据或登录凭据。Python测试用 .venv/Scripts/python.exe -m pytest -q；DOM适配测试用 npm test。
