# DESIGN_NOTES — 设计决策与踩坑记录（ADR 风格，滚动追加）

> 规则（见 CLAUDE.md）：
> - 记录"决策与理由"，不记录"代码现在怎么跑"（那属于代码注释）；
> - 决策被推翻时**追加**"后续：改为 X"，不删原文；
> - 每条带日期，按时间倒序或正序均可，保持正序追加。

---

## 2026-09-08 踩坑：本机 5432 端口被其他项目占用

- **现象**：`docker compose up` 报 `Bind for 0.0.0.0:5432 failed: port is already allocated`。
- **原因**：同机另一个项目（cookhero）的 postgres 容器随 Docker Desktop 自启动，占了 5432。
- **解决**：NutriLens 改用宿主机 5433（`docker-compose.yml` / `.env.example` / `config.py` 三处同步）。
- **教训**：多项目共用一台开发机时，compose 端口别都抢 5432 默认值；Navicat 连接时注意端口是 5433。

## 2026-09-08 踩坑：Git Bash 下 curl 传中文 JSON 解析失败

- **现象**：FastAPI 返回 `{"detail":"There was an error parsing the body"}`。
- **原因**：Windows Git Bash 的 `curl -d '中文'` 按 GBK 编码发出，服务端按 UTF-8 解析失败。
- **解决**：中文 body 写入 UTF-8 临时文件，用 `curl --data-binary @file` 发送。
- **教训**：Windows 下做接口联调，含非 ASCII 的请求体一律走文件；测试里用 TestClient（进程内）可完全绕开。

## 2026-09-08 踩坑：跨 Session 删除 ORM 父对象报错（fixture 清理）

- **现象**：测试 teardown 中 `db.delete(user)` 抛错（用户在另一个 SQLAlchemy Session 里被关联了 UserProfile）。
- **原因**：ORM 删父对象时会懒加载 relationship 子对象并尝试把子表外键置 NULL；`user_profiles.user_id` 是主键非空，置 NULL 失败。
- **解决**：清理时先显式删子行（profile）再删父行；或用 bulk delete（`query().delete()` 绕过 ORM 层，交给 DB 外键 ON DELETE CASCADE）。
- **教训**：多 Session 场景（Agent 工具每次调用独立 Session）下，测试清理不要依赖 ORM 级联感知。

## 2026-09-08 决策：饮食写库走 HITL，运动直接落库

- **背景**：两条写库路径一个用 `interrupt()` 请求人工确认，一个直接写。
- **理由**：HITL 的成本是打断交互，收益是拦住不可信数据。饮食克数由 VL 模型估算、误差大 → 值得拦；运动的"类型+时长"由用户亲口陈述、无估算环节 → 拦了纯添堵。
- **面试口径**：同一项目里两种策略并存，说明 human-in-the-loop 是按"数据可信度"做工程取舍，不是流程装饰。

## 2026-09-08 决策：档案更新业务逻辑从路由下沉到 service

- **背景**：M3.2 之前，"部分更新档案 + 重算 BMR/TDEE"写在 `api/users.py` 的 PUT 处理函数里。
- **理由**：Agent 工具（`tools/profile.py`）需要同一逻辑；按项目纪律 REST 与工具共用 service 层，于是先下沉再复用，路由变薄。
- **验证**：回归测试断言 REST 行为与下沉前的冒烟手算值完全一致（1648.8/2555.6/2055.6）。

## 2026-09-08 决策：数据库端口/凭据用默认值兜底，服务可裸跑

- **理由**：`config.py` 所有字段给了默认值（密钥为空串），无 `.env` 也能起服务——冒烟测试与单元测试不依赖外部凭据；只有调 LLM/OSS 的功能才需要真 key。
