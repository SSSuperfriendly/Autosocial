# 参与 AutoSocial

欢迎帮助申请者更清楚地管理导师联系进度。提 Issue 时，请描述实际场景、当前行为和期望行为。不要附上真实导师邮箱、完整回信、个人简历或密钥。

## 开发环境

使用 Python 3.11+、Node.js 22+。从仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m autosocial init-db
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

前端在 http://localhost:5173，Vite 将 `/api` 请求代理到后端。开发时使用独立的本地数据，不连接生产邮箱；需要样例时在空库中运行 `python scripts/seed_demo.py`。

## 验证

```bash
python -m unittest discover -s tests -v
python scripts/test_local.py
python scripts/check_privacy.py
cd frontend
npm ci
npm run build
```

CI 运行后端单元/回归测试、原子写入测试、前端构建，以及 Docker 构建、鉴权和重启后数据保留的冒烟检查。涉及跟进日期、状态变更、数据迁移、邮件行为或访问保护时，请覆盖重要的行为边界。界面改动需检查空状态、窄屏、加载失败与键盘操作。

## 提交修改

1. 从最新代码创建分支，围绕一个具体使用场景修改。
2. 说明问题、修改后的行为和实际执行的验证。
3. 展示界面时使用虚构数据，避免上传 `.env`、SQLite、备份或导出的联系人。
4. 涉及存储结构时保持现有数据库可升级，避免破坏已有沟通进度。

当前重点是单人自托管的博士申请跟进。多人账户、大规模自动外联和自动发送催信会改变架构与产品边界，请先讨论方案。
