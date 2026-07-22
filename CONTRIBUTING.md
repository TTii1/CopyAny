# 贡献指南 Contributing

感谢你对 CopyAny 的关注！无论是报告问题、提出建议还是提交代码，都非常欢迎。

## 报告问题（Issues）

提交 Issue 时建议包含：

- 操作系统与版本（如 Windows 11 23H2 / Ubuntu 24.04，X11 还是 Wayland）
- CopyAny 版本（Release 版本号或源码 commit）
- 复现步骤、期望行为与实际行为
- 日志片段：`%APPDATA%\CopyAny\copyany.log`（Windows）或 `~/.config/copyany/copyany.log`（Linux）
  —— 注意脱敏，日志中不要包含你的共享密钥

## 提交代码（Pull Requests）

1. Fork 本仓库并创建特性分支：`git checkout -b feature/xxx`
2. 保持代码风格与现有代码一致（纯标准库 + PySide6，尽量无新增依赖）
3. 改动后请通过自检：

   ```bash
   python run.py --selftest
   ```

4. 提交 PR 时说明改动动机与测试情况（建议在 Windows 和 Linux 各验证一次）

## 开发环境

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py            # 运行
python run.py --selftest # 核心自检（加密 / 存储 / 双节点同步）
```

## 行为准则

请保持友善与尊重。本项目规模不大，沟通直接高效即可。
