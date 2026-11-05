# 评测数据工具

所有工具使用 Python 3 标准库。`export_games.py` 只读解析 Next-Makyek 的公开比赛页面和日志，不执行网页脚本，不读取浏览器 Cookie 或密码。

平台地址、用户 ID 和默认提交地址通过 `config/local.json` 配置；示例在 `config/example.json`。也支持 `GOMOKU_JUDGE_URL`、`GOMOKU_USER_ID`、`GOMOKU_SUBMISSION_URL` 环境变量。不要提交本地配置或原始对手数据。

```sh
python3 scripts/export_games.py --submission 'http://judge.example:18080/submission/SUBMISSION_ID'
python3 scripts/judge_status.py --base-url 'http://judge.example:18080' --user-id USER_ID --queue
python3 scripts/compare_submissions.py --baseline OLD_ID --challenger NEW_ID
```

导出会缓存已完成局，写入 `data/<id>/index.json`、`rounds/`、`logs/` 和 ZIP；重复运行用于补齐新局。必须核对 pending、errors 与索引范围，再使用相同对手提交和执色比较。比赛分为 3/1/0，小局分析分为 1/0.5/0，两种指标不能混用。

`check_release.py` 是 `make check-size` 的入口，分别检查源码和本机可执行文件不超过 1 MiB，并核对当前源码指纹。
