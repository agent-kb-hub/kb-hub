# 数据字典

## Hub 知识条目字段

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| id | string | 自动生成 | 唯一标识，格式 `hub-{content_hash}` 或 `hub-sync-{content_hash}` |
| title | string | ✅ | 知识标题，建议 ≥8 字 |
| summary | string | ✅ | 知识摘要，建议 ≥50 字 |
| quality | number | ✅ | 质量分 0-100，≥60 才接受入库（Hub 自动评估覆盖节点提交值） |
| topics | array | ❌ | 主题标签列表，如 `["可信数据空间", "政策"]` |
| tags | array | ❌ | 辅助标签（用于搜索匹配） |
| source | string | ❌ | 来源，如 "数据要素政策研究" |
| source_date | string | ❌ | 来源日期，格式 `YYYY-MM-DD` |
| url | string | ❌ | 原文链接，用于溯源，必须是 https/http 开头 |
| category | string | ❌ | 分类，默认 "其他"，可选：行业政策/新闻资讯/金融资本/产品方案/技术资料/数据资产/其他 |
| archive_url | string | ❌ | 存档链接（如网页快照） |
| source_node | string | 自动填入 | 来源节点名，如 `domi-cloud` |
| created_at | string | 自动填入 | 入库时间，格式 `YYYY-MM-DD HH:MM:SS` |
| updated_at | string | ❌ | 更新时间 |
| usage_count | number | 自动维护 | 本地查询使用次数（本地 TinyDB 维护） |
| last_used | string | 自动维护 | 最后使用时间 |
| hub_usage_count | number | 自动维护 | Hub 查询使用次数（Hub DB 维护） |
| hub_last_used | string | 自动维护 | Hub 最后使用时间 |

## config.json 字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| port | int | HTTP 服务端口，默认 10128 |
| host | string | 监听地址，默认 0.0.0.0 |
| hub_db_path | string | Hub 数据库路径，相对于 HUB_DIR |
| local_db_path | string | 本地知识库 TinyDB 路径 |
| log_path | string | 审计日志路径（相对路径，相对于 HUB_DIR） |
| rate_limit_per_node | int | 每节点速率限制（次/窗口），默认 100 |
| rate_limit_window_seconds | int | 速率限制窗口（秒），默认 60 |
| quality_threshold | number | 入库质量门槛，默认 60 |
| max_item_size_bytes | int | 单条最大字节数，默认 10240 |
| nodes | object | 节点名称 → {token, role, description} |

## 节点角色

| 角色 | 权限 |
|------|------|
| admin | 读写删，可查看所有节点 token |
| writer | 读写，可提交知识和同步 |
| reader | 只读，只能查询 |

## topic_map 主题映射

key = 标准主题名，value = 别名数组，用于查询时归一化。

## API 错误码

| HTTP 状态 | body.error | 说明 |
|-----------|-----------|------|
| 401 | — | 缺少或无效的 Authorization header |
| 403 | — | Token 无效，或节点权限不足 |
| 429 | — | 速率限制超限（100次/分钟） |
| 400 | — | 请求参数错误 |

## /ingest skipped 原因

| reason | 说明 |
|--------|------|
| duplicate | 内容去重（title+summary hash 相同） |
| quality_too_low | 自动评估质量分 < 60 |
| too_large | JSON 序列化后超过 max_item_size_bytes |