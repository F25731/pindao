# 光鸭资源检索 AstrBot 插件

这个插件只负责检索，不负责推送。

## 命令

- `/gy 关键词`：搜索资源
- `/gy_more`：继续下一页
- `/gy_detail 序号`：查看当前结果中的某条详情
- `/gy_detail 资源ID`：直接查看指定资源详情
- `/gy_reset`：清空当前会话缓存
- `/gy_status`：检查检索接口

## 配置

- `api_base`：光鸭资源系统后端地址
- `api_key`：具备 `search:read` 权限的 API 密钥
- `default_limit`：默认返回条数
- `session_ttl_seconds`：会话缓存时间
- `status`：可选，只检索某个状态

## 使用建议

如果资源量很大，建议每次保持 10 条左右，靠 `/gy_more` 翻页，再用 `/gy_detail` 查看单条详情。
