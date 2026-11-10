# 周报整合系统

Vue 3 + Django + PostgreSQL + Celery + MinIO + Gotenberg

## 一键部署（生产环境）

```bash
git clone -b dev https://github.com/guoyi248/zhoubao_fix.git weekly-report
cd weekly-report
chmod +x deploy/setup.sh
./deploy/setup.sh
```

部署完成后访问 `http://<服务器IP>:9527`。首次创建的管理员账号为 `admin`，随机登录密码在创建账号时输出。已有部署的管理员沿用原密码，仍使用旧版初始密码时可在「用户管理」中重设。

### 前置要求

- Debian 11/12/13 或 Ubuntu 20.04+
- Docker 已安装运行（`docker ps` 能跑）
- Python 3.11+

### setup.sh 做了什么

1. 检测 Python、pip、Docker、openssl，缺失自动安装
2. 创建目录和密钥（`deploy/secrets/`）
3. 生成 `deploy/config/app.env` 环境变量
4. 启动 Docker 服务：PostgreSQL、Redis、MinIO、Gotenberg、ClamAV
5. 创建 MinIO 存储桶
6. 安装 Python 依赖
7. 数据库迁移
8. 创建管理员账号
9. 启动 Nginx（反向代理 + 前端静态文件）
10. 启动 Gunicorn（Django API）

### 对外入口与已有文件存储

生产部署默认通过 Nginx 的 9527 端口访问。数据库、Redis、附件存储、文档转换与扫描服务通过容器网络互通。

一键部署会为新安装的内置 MinIO 生成随机凭据。升级有历史附件的部署时，保留原项目的 MinIO 容器、`data/minio`、`deploy/secrets` 和 `deploy/config/app.env`。脚本会复用已有凭据。若旧容器已删除，或之前使用文件注入凭据，先将原来的 root 账号和密码分别写入 `deploy/secrets/minio_root_user` 和 `deploy/secrets/minio_root_password`，再运行 `deploy/setup.sh`。

使用外部 S3 时，在 `deploy/config/app.env` 保留后端可访问的服务地址、访问凭据及已创建的桶名称。手工通过 Compose 启动内置 MinIO 时，使用 `--profile bundled-storage`。

### 自定义端口

编辑 `deploy/compose.production.yaml`，修改 Nginx 的 `ports` 即可：

```yaml
nginx:
  ports:
    - "你的端口:80"
```

同时修改 `deploy/config/app.env` 中对应服务的连接地址。

## 开发环境

在 Windows 上，安装 Python 和 Node.js 后可双击 `scripts/start.bat`，一起启动本地页面、接口和后台任务。默认使用 SQLite。窗口会显示本次预览地址。默认端口已占用时，启动脚本会尝试使用页面端口 5174 和接口端口 8001。

### 后端

```bash
cd backend
python -m pip install -e "..[dev]"
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

本地开发默认使用 SQLite 和本地附件目录。配置 `S3_ENDPOINT` 及访问凭据后使用 MinIO。生产环境的上传、替换和更正都会调用 ClamAV，单机开发可设置 `CLAMAV_HOST` 启用扫描。

### Word 原文预览

系统从上传的 Word 原件生成 PDF，组会、周报详情和提交确认都使用这份预览。生产部署使用 `GOTENBERG_URL` 指定的 Gotenberg 服务。本机运行时可以安装 LibreOffice，系统会查找常规安装目录和 PATH；也可以在 `backend/.env` 设置 `LIBREOFFICE_BINARY` 为 `soffice.com`（Windows）或 `soffice` 的完整路径，然后重启接口和后台任务。转换机应具备周报使用的字体。缺少字体时，部分换行和分页可能与作者电脑上的 Word 不同。

从旧版升级后，先运行 `python backend/manage.py repair_word_previews --dry-run` 查看需要重建的 Word 预览，再运行 `python backend/manage.py repair_word_previews`。该命令从原附件重建早期的纯文本预览，以及含有 Word 原生公式（Office Math）的旧版式预览。成员无需重新上传或提交。

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`

### Docker 基础设施（开发用）

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up -d postgres redis minio clamav
```

## 账号与工作台

- 普通用户可以在浅绿色工作台提交、更正和回看自己的周报，查看自己的解析、提醒与个人计划。
- 管理员还可以查看团队周报、进入全屏组会、管理用户和配置系统。工作台的已交和待交名单均按所选周的实际记录生成。组会左侧点姓名切换成员。在任一周报阅读区按住 Ctrl，向上滚动鼠标滚轮放大，向下滚动缩小。松开 Ctrl 后可以滚动阅读多页文档。缩放比例会在此浏览器中记住，切换周报时继续使用。
- 「用户管理」支持创建账号、复制激活链接、编辑资料和角色、停用、恢复及删除账号。删除会撤销登录资格并保留历史周报及操作记录。旧版超级管理员在迁移后归入管理员角色。
- 「操作记录」可查看登录时间、来源 IP、地点及周报文件和提交版本的变动。地点按连接来源估算。局域网可在部署环境设置 `AUDIT_LOCATION_NETWORKS=10.10.1.0/24=实验室`。内置生产部署通过 nginx 核对客户端 IP。自定义代理可用 `AUDIT_TRUSTED_PROXIES` 指定可信代理的 IP 或网段，或用 `AUDIT_TRUSTED_PROXY_HOSTS` 指定可信代理的主机名，由代理覆盖 `X-Real-IP`。如需公网城市归属地，将后台可读取的本地城市库路径填入 `AUDIT_GEOIP_DATABASE`。API 镜像已包含 `geoip` 依赖，本机开发可用 `python -m pip install -e ".[geoip]"` 安装。无法定位的来源会显示未知。

## 组内知识库

已激活的成员和管理员登录后都可阅读组内知识库。首页选择知识空间，沿左侧目录树打开文章，也可以搜索标题或正文。浏览器地址可直接分享给其他组内成员。预置的「组内指南」包含周报与组会说明、实验记录模板和知识库编写指南。

管理员可以新建空间和多级目录、移动文章，或导入 UTF-8 编码的 `.md`、`.markdown` 文件并预览。文章支持表格、代码块、图片及页内目录。普通成员使用只读视图。

迁移已备份的 Apifox 分享快照时，先运行数据库迁移，再运行 `python backend/manage.py import_apifox_knowledge <快照目录>/manifest.json`。保留快照旁的图片文件。命令以来源 ID 匹配文章和目录，重复执行保留已有链接及本地编辑。知识库图片与附件使用同一存储服务，访问图片需要登录。

## 周末提醒和周进展总结

管理员在「系统配置 → AI 模型」选择在线模型或 Ollama，填写服务地址、模型名和所需密钥。周报解析和右下角的桌宠「大肥鱼」共用这套配置，保存后下一次调用生效。桌宠仅向模型发送用户输入的对话，点击角色即可聊天。邮件提醒和附件限制分别在对应标签页管理。

在页面输入的凭据加密后存入数据库。设置页只显示是否已配置，留空会保留已有密钥，切换服务商或地址后需重新填写。升级时执行数据库迁移，并保留该部署原有的 Django 主密钥。单机开发环境使用默认 Django 密钥时，本地加密文件位于 `backend/config/secrets/integrations.key`。

新安装的生产环境单独保管主密钥文件 `deploy/secrets/django/key`。备份时与业务数据分开保管。旧安装如改用文件主钥，须将**正在使用的同一把** `DJANGO_SECRET_KEY` 安全放入此文件，在环境中设置 `DJANGO_SECRET_KEY_FILE=/run/secrets/weekly-django/key` 并移除旧的 `DJANGO_SECRET_KEY`。宿主的 `deploy/secrets` 目录仅部署账号可进入，容器内的应用进程需能读取挂载的文件。

通过环境文件管理模型的部署，可在配置好 `LLM_PROVIDER` 和 `LLM_BASE_URL` 后，在同一部署中运行 `python backend/manage.py encrypt_model_key`。命令隐藏输入的 API 密钥，输出一行 `LLM_API_KEY_ENCRYPTED=…`。将这一行写入生产的 `deploy/config/app.env` 或开发的 `backend/.env`。若旧部署已配置明文 `LLM_API_KEY`，可在升级后的 API 容器中运行以下命令，复制输出的密文替换原明文配置行，再让服务重新读取环境。既有环境文件的内容需要由服务器管理员完成替换。

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml exec api python backend/manage.py encrypt_model_key --from-env
```

替换环境文件中的配置行后，执行 `docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d --force-recreate api worker scheduler` 载入密文。

### 邮件提醒

设置 `ENABLE_WEEKLY_REMINDERS=true`、成员可打开的 `WEEKLY_SITE_URL`、`DEFAULT_FROM_EMAIL`、`EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_HOST_USER` 和 `EMAIL_HOST_PASSWORD`。587 端口通常用 `EMAIL_USE_TLS=true`，465 端口通常用 `EMAIL_USE_SSL=true` 并关闭 TLS 开关。成员可在「邮箱提醒」保存自己的收件地址并查看提醒时间。管理员可在同一页查看未交名单及本周成功发送记录，也可到「用户管理」维护邮箱。

默认在工作区时区（北京时间）周日 18:00 起检查，直到这周的截止时间。使用 `REMINDER_WEEKDAY`（周一为 1，周日为 7）和 `REMINDER_TIME`（24 小时制）调整。提醒只发给有邮箱、已激活且本周尚未提交的账号，包含管理员。已提交后正在更正的成员算已交。成功交付后记录当周回执，临时发送失败会在窗口内重试。

### 大模型解析

设置 `ENABLE_LLM=true` 后，新提交及更正的每一版周报都会排队解析。每次只向所选模型发送这一版的正文和附件文字。可解析文本文件和带文字层的 PDF，Office 文件使用转换后的预览。纯图片扫描件需先进行 OCR。成员可在「AI 周报解析」按周查看自己的总结，管理员可在同一页按周、按成员查看。团队周报中的「组会展示」进入全屏投影页，左侧切换成员，右侧显示该周报的原文。对启用前已提交的版本，打开详情后点「生成总结」。

- OpenAI 兼容服务使用 `LLM_PROVIDER=openai_compatible`，`LLM_BASE_URL` 填服务提供的 API 基础地址（通常以 `/v1` 结尾），并填写 `LLM_MODEL` 和该地址对应的 `LLM_API_KEY_ENCRYPTED`。
- Ollama 使用 `LLM_PROVIDER=ollama`，`LLM_MODEL` 填已经下载的模型名，例如 `qwen2.5:7b`。本机直接运行时，`LLM_BASE_URL=http://127.0.0.1:11434`。Docker 连接宿主机时可用 `http://host.docker.internal:11434`，Ollama 需要监听容器可访问的地址。未开启认证的 Ollama 可留空密钥。
- `LLM_MAX_INPUT_CHARS` 控制每次发送的原文字符预算，多附件共享额度。总结会标出跳过或截取的内容。

### 启动后台处理

生产一键部署会启动 worker 和 scheduler。从旧版首次升级到本版时，按上文准备原存储凭据后运行 `./deploy/setup.sh`，使新的端口和存储配置生效。此后日常更新可在项目目录执行以下命令。

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml build api nginx worker
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python backend/manage.py migrate
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d api nginx worker scheduler
```

在 Windows 或其他单机开发环境，启动前后端后，再在同一个 Python 环境单独运行以下命令，并保持该进程在线。新提交的周报会先保存，后台再生成总结。

```bash
python backend/manage.py migrate
python backend/manage.py run_weekly_jobs --watch
```

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite 8.x + Element Plus + Pinia |
| 后端 | Python 3.13 + Django + DRF |
| 异步 | Celery 5.6 + Redis 7 |
| 数据库 | PostgreSQL 17 |
| 存储 | MinIO (S3 兼容) |
| 转换 | Gotenberg (LibreOffice) |
| 安全 | ClamAV + Django Session + CSRF + Argon2 |
| 部署 | Docker Compose + Nginx + Gunicorn |

## 项目结构

```
├── backend/              # Django 模块化单体
│   ├── config/           # 设置、URL、Celery、WSGI
│   ├── accounts/         # 用户、角色、TOTP
│   ├── organizations/    # 部门
│   ├── reporting/        # 周期、周报、修订
│   ├── attachments/      # 上传、扫描、预览
│   ├── analysis/         # LLM 分析
│   ├── meetings/         # 组会
│   ├── private_plans/    # 个人计划
│   ├── audit/            # 审计
│   ├── system_config/    # 系统配置
│   └── common/           # 共享基础设施
├── frontend/             # Vue 3 SPA
├── docker/               # Dockerfile（可选）
├── deploy/               # Compose、Nginx 配置
│   └── setup.sh          # 一键部署脚本（入口）
└── README.md
```
