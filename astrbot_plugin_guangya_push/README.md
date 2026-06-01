# 光鸭资源推送 AstrBot 插件

这个插件用于连接光鸭资源自动转存系统和 AstrBot 的 Telegram 机器人。

流程：

1. 插件调用后端 `POST /api/external/push/lease` 领取待推送资源。
2. 后端把资源锁定为 `推送中`，避免重复推送。
3. 插件把返回的 `text` 发到绑定的 Telegram 会话。
4. 插件调用 `POST /api/external/push/callback` 回写成功或失败。

推送格式：

```text
名称：资源名
标签：标签
链接：你的网盘链接
```

## 安装

把 `astrbot_plugin_guangya_push` 整个目录放到 AstrBot 的插件目录，例如：

```bash
cp -r astrbot_plugin_guangya_push /path/to/AstrBot/data/plugins/
```

然后在 AstrBot 管理面板里重载插件或重启 AstrBot。

## 配置

需要配置：

- `api_base`：光鸭资源系统后端地址，例如 `http://154.201.75.36:8000`
- `api_key`：后台「API 密钥」里创建的密钥
- `target_unified_msg_origin`：目标会话，可以用命令绑定

## 命令

- `/gy_bind_push`：把当前会话绑定为推送目标
- `/gy_push_status`：检查后端 API 和待推送数量
- `/gy_push_once`：手动领取并推送一批
- `/gy_push_pause`：暂停自动轮询
- `/gy_push_resume`：恢复自动轮询

