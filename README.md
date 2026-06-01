# 光鸭网盘资源自动转存系统

光鸭网盘资源自动转存 + 网站管理 + Telegram 推送系统。

## 功能

- Excel 批量导入资源（名称、标签、链接）
- 自动解析光鸭分享链接
- 精确去重 + 疑似重复人工审核
- 多账号池自动转存到自己的光鸭账号
- 转存成功后自动生成新分享链接
- 导出新 Excel（链接替换为自己的分享链接）
- 提供 API 给 AstrBot 插件拉取待推送资源
- 推送到 Telegram 频道
- Docker 一键部署

## 快速开始

### 环境要求

- Docker + Docker Compose
- Git

### Docker 一键部署

```bash
git clone <your-repo-url>
cd guangya-resource-bot

# 复制环境变量配置
cp .env.example .env

# 修改 .env 中的关键配置
# - SECRET_KEY: 改为随机字符串
# - ADMIN_USERNAME / ADMIN_PASSWORD: 管理员账号密码
# - POSTGRES_PASSWORD: 数据库密码

# 启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 运行数据库迁移
docker compose exec web alembic upgrade head
```

启动后访问:
- 前端管理后台: http://localhost:5173
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 本地开发

```bash
# 后端
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev

# Worker
cd backend
python -m app.worker.main
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| SECRET_KEY | JWT 加密密钥 | dev-secret-key |
| ADMIN_USERNAME | 管理员用户名 | admin |
| ADMIN_PASSWORD | 管理员密码 | admin123 |
| DATABASE_URL | PostgreSQL 连接 | postgresql+asyncpg://postgres:postgres@db:5432/guangya |
| REDIS_URL | Redis 连接 | redis://redis:6379/0 |
| WORKER_MAX_CONCURRENT | Worker 最大并发 | 2 |
| WORKER_POLL_INTERVAL | Worker 轮询间隔(秒) | 10 |
| WORKER_MAX_RETRIES | 最大重试次数 | 3 |

## 后台管理

登录后可使用以下功能:

1. **运行统计** - 总览各状态资源数量、今日处理量、账号状态
2. **Excel 导入** - 上传 Excel，自动解析、去重、创建任务
3. **导入批次** - 查看历史导入记录和统计
4. **资源列表** - 按状态筛选、搜索资源
5. **任务队列** - 查看转存任务执行状态
6. **重复审核** - 疑似重复资源左右对比，批量操作
7. **失败任务** - 查看失败原因，手动重试
8. **账号池** - 管理光鸭账号，查看状态和用量
9. **导出 Excel** - 按条件导出，链接替换为新分享链接
10. **推送管理** - 查看待推送和已推送资源
11. **API 密钥** - 管理外部 API 访问密钥

## Excel 格式要求

| 名称 | 标签 | 链接 |
|------|------|------|
| 资源名称 | 标签1,标签2 | https://www.guangyapan.com/s/xxx?code=yyy |

## 账号池使用

1. 在后台「账号池」页面添加光鸭账号
2. 需要提供 access_token 和 refresh_token
3. 系统自动选择可用账号进行转存
4. 账号容量满/失效/风控时自动切换

## 转存任务机制

- Worker 后台长期运行，每次最多处理 2 个任务
- 每个任务带 checkpoint，重启后断点续跑
- 失败自动重试（指数退避），最多 3 次
- 不可恢复错误直接标记最终失败

## 去重和审核机制

**精确去重（自动跳过）:**
- 相同链接
- 相同 share_id + 提取码
- 批次内重复
- 数据库已存在

**疑似重复（人工审核）:**
- 名称相似度 > 80%
- 标签重叠 > 50%
- 支持批量操作：跳过/都保留/使用当前/保留已有

## Telegram 推送

转存成功的资源自动进入「待推送」状态。

外部 API（给 AstrBot 插件使用）:
- `GET /api/external/push/pending` - 只查看待推送资源，不锁定
- `POST /api/external/push/lease?limit=10` - 领取一批待推送资源，并锁定为「推送中」
- `POST /api/external/push/callback` - 回调标记已推送/失败
- 需要 `X-API-Key` header 认证

AstrBot 插件建议流程:
1. 定时调用 `POST /api/external/push/lease` 领取资源
2. 使用返回的 `text` 字段直接发送 Telegram，格式为：
   ```
   名称：xxx
   标签：xxx
   链接：xxx
   ```
3. 成功后回调：
   ```json
   {"resource_id": 1, "status": "success", "message_id": "telegram message id"}
   ```
4. 失败后回调：
   ```json
   {"resource_id": 1, "status": "failed", "error_message": "错误原因"}
   ```
5. 如果插件宕机导致资源停在「推送中」，后台「推送管理」可以一键恢复卡住的推送。

## 升级

```bash
cd guangya-resource-bot
git pull
docker compose up -d --build
docker compose exec web alembic upgrade head
```

## 备份数据库

```bash
docker compose exec db pg_dump -U postgres guangya > backup_$(date +%Y%m%d).sql
```

## 常见问题

**Q: Worker 没有处理任务？**
A: 检查 `docker compose logs worker`，确认账号池有可用账号。

**Q: 转存失败「账号登录失效」？**
A: 账号的 token 过期了，需要重新获取 access_token 和 refresh_token 并更新。

**Q: 导入后全部显示「解析失败」？**
A: 检查 Excel 中的链接格式是否为 `https://www.guangyapan.com/s/xxx?code=yyy`。
