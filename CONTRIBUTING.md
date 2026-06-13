# Contributing to CodePilot

欢迎贡献！以下是参与开发的指引。

## 开发环境

```bash
git clone https://github.com/jkrandom-sudo/codepilot.git
cd codepilot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 代码规范

- 使用 [ruff](https://docs.astral.sh/ruff/) 进行 lint 和格式化
- 类型注解优先使用 `from __future__ import annotations`
- 提交前运行：`ruff check codepilot evals tests`

## 测试

- 使用 pytest 运行测试：`pytest tests/ -q`
- 新增功能必须包含测试
- 使用 pytest-asyncio 测试异步代码

## 提交 PR

1. 从 `main` 创建新分支
2. 提交有意义的 commit message
3. 确保所有测试通过
4. 提交 PR 到 `main`

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CODEPILOT_WORKING_DIR` | 工作目录 | 当前目录 |
| `CODEPILOT_TRUNCATION_DIR` | 输出截断文件存储路径 | `~/.codepilot/truncations` |
| `LANGSMITH_API_KEY` | LangSmith 追踪 API Key | — |
| `LANGSMITH_PROJECT` | LangSmith 项目名 | `codepilot` |
