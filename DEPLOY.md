# 部署、更新与备份

推荐每位申请者部署自己的单实例。数据库、画像、模板和附件留在自己的服务中；同一实例不提供多用户隔离。

## Docker 部署

```bash
cp .env.example .env
# 编辑 .env，填写 AUTOSOCIAL_PASSWORD（至少 12 字符）
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 autosocial
```

默认入口为 http://127.0.0.1:8000，用户名 `autosocial`。浏览器会弹出 HTTP Basic 登录框。Docker 强制密码保护；密码缺失或过短会阻止启动。`/health` 无需登录，只返回健康检查结果；页面、API、文档和静态资源均受保护。

容器以非 root 用户运行，服务只运行一个 worker。`/app` 为应用代码，`/state` 为运行数据。Compose 逻辑卷名为 `autosocial-data`，实际 Docker 卷名带有 Compose 项目前缀。

| 容器路径 | 内容 |
| --- | --- |
| `/state/data/autosocial.db` | 导师、草稿、发送记录、回信和沟通时间线 |
| `/state/data/` | 研究偏好、目标学校、检索提示词、附件 |
| `/state/student_profile.md` | 个人背景 |
| `/state/templates/email_template.md` | 写信模板 |
| `/state/backups/` | 备份（默认目录） |

首次启动自动初始化缺少的文件，已有数据库通过增加字段和表升级，不重建用户资料。保留同一个 Compose 项目名和卷，更新才能继续使用原来的数据。

## 公网 HTTPS

Compose 默认只将端口映射到主机回环地址。不要直接将免密本地开发服务映射到公网。

有域名时，在同一台服务器上安装 Caddy，将域名指向服务器，并使用类似配置：

```caddyfile
apply.example.com {
    reverse_proxy 127.0.0.1:8000
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
```

开放反向代理需要的 80/443 端口，保留应用端口仅本机可访问。HTTP Basic 需要 HTTPS 保护传输；常规 Caddy 反向代理保留 Host 并传递协议信息，应用的跨站写入检查依赖正确的 Host / scheme。若使用其他代理，请正确设置受信任代理，不要无条件信任公网传入的代理头。

Docker 经宿主机代理时可能无法识别外部 HTTPS 协议。在 `.env` 中明确设置公开入口（不含路径），然后重新创建容器：

```dotenv
AUTOSOCIAL_PUBLIC_ORIGIN=https://apply.example.com
```

```bash
docker compose up -d
```

应用以该值验证浏览器写入来源，不需要为此信任任意代理头。CORS 默认只允许本地 Vite 开发地址；使用独立前端时，设置 `AUTOSOCIAL_CORS_ORIGINS` 为逗号分隔的精确来源，不使用 `*`。

## 更新

先备份，再在自己的代码仓库更新：

```bash
docker compose exec autosocial python -m autosocial.backup
git pull --ff-only
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
```

`docker compose down` 保留数据卷；`docker compose down -v` 会删除数据卷，不能用于日常更新。降级到旧代码前，需同时恢复兼容的备份；新结构不保证被旧版本识别。

## 备份与恢复

SQLite 使用 WAL，不能通过只复制 `.db` 文件获得可靠备份。内置备份命令使用 SQLite backup API 生成数据库快照，并打包偏好、画像、模板和附件：

```bash
# 容器
# 返回如 backups/autosocial-20261122T120000000000Z.tar.gz
docker compose exec autosocial python -m autosocial.backup
docker compose cp autosocial:/state/backups ./backups

# 本地，先激活虚拟环境
python -m autosocial.backup --output backups
```

备份包含个人数据，文件权限默认设为 `600`。它不打包 `.env`；请单独安全保管密码和外部服务配置。完整迁移时，尽量在没有操作界面、写信或同步任务时执行，定期将备份复制到另一台设备。备份保留策略由部署者管理。

恢复到**空实例**，或先备份已有实例并明确决定覆盖后，使用 Bash：

```bash
docker compose stop autosocial
# 将下面文件名替换为你的备份；backups目录需位于当前项目根目录。
docker compose run --rm --no-deps \
  --volume "${PWD}/backups:/backup:ro" \
  --entrypoint sh autosocial \
  -c 'cd /state && tar -xzf /backup/autosocial-YOUR-BACKUP.tar.gz'
docker compose up -d
```

仅恢复自己信任的备份。`tar` 会覆盖同名文件；若要精确回到旧快照，先将当前运行数据整体移到安全位置，再恢复，避免保留快照中不存在的新增文件。默认数据库恢复位置为 `/state/data/autosocial.db`；本地使用自定义 `DATABASE_PATH` 时，应将备份中的该文件移至自己的配置路径。

## 已有 systemd / Caddy 部署

仓库保留 `deploy/scripts/deploy_oracle_ubuntu.sh` 和 `deploy/scripts/deploy_update.sh`，兼容现有 Ubuntu / Debian 单实例。旧脚本需要 sudo、会安装系统依赖并操作 systemd，首次自托管建议优先使用 Docker。

更新前使用现有备份脚本：

```bash
sudo bash deploy/scripts/backup_sqlite.sh
```

生产环境配置位于 `/etc/autosocial/autosocial.env`。请设置独立密码并启用 `AUTOSOCIAL_REQUIRE_AUTH=true`。systemd 服务会强制要求访问保护，避免升级后使用旧配置继续免密运行。首次安装脚本会在缺少有效密码时生成随机密码，仅写入权限受限的环境文件，不将密码输出到日志。

旧版数据保留在 `/var/lib/autosocial/`，由原有软链接映射到应用目录。服务启动时自动迁移 SQLite。部署机器、SSH 主机名与私钥不再在通用发布脚本中预填；维护自己的 SSH 配置，并查看脚本参数后使用。`deploy/ORACLE.md` 为历史安装细节，当前密码保护与数据说明以本文为准。

## 检查与故障排查

- **启动时提示密码错误**：检查 `.env` 中密码至少 12 字符；不要把真实密码提交到 Git。
- **出现 401**：使用浏览器登录框输入实例用户名和密码。修改密码后需重新认证。
- **出现 403 跨站写入**：在 `.env` 设置正确的 `AUTOSOCIAL_PUBLIC_ORIGIN=https://你的域名` 并重新创建容器；检查反向代理 Host；独立前端添加精确 CORS 来源。
- **没有前端页面**：本地执行 `cd frontend && npm ci && npm run build`；Docker 会在构建阶段完成。
- **模型或邮箱未配置**：手动跟进和模板草稿仍可使用；搜索与邮箱操作需要对应配置和网络。
- **迁移 Docker**：从旧环境创建完整备份，在新卷恢复；不要复制运行中的单个 `.db` 文件。

技术参考：[FastAPI HTTP Basic](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/)、[Docker Compose services](https://docs.docker.com/reference/compose-file/services/)。

SMTP 超时或连接中断导致投递结果不明时，发送记录会保留 `sending`，阻止再次投递。请先在发件箱核对实际投递结果，再由维护者检查该记录；当前版本不提供自动重试或解锁按钮。
