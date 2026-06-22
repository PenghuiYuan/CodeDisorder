# CodeDisorder

> 代码混淆 Web 服务:为 C / C++ / Python / Java / Go 源码提供 AST 级别的结构混淆,生成可在目标 OJ(Codeforces / 牛客 / AtCoder / 学习通 / PTA)直接提交且不被查重系统判定为重复的完整可编译源码。

## 快速启动

```bash
# 克隆仓库
git clone https://github.com/yph19990803/CodeDisorder
cd CodeDisorder

# 启动服务(前端 + API + Worker)
docker-compose up

# 访问 http://localhost:8000
```

## 文档

- [需求文档 SPEC.md](SPEC.md) —— 目标、范围、接口、UI 规范、上线扩展点预留。
- [设计文档 DESIGN.md](DESIGN.md) —— 架构、模��划分、关键算法、每日 todo。

## 技术栈

**后端**:
- Python 3.11+ (PyClang for libclang, ast for Python)
- FastAPI 0.110+ (异步 API + Pydantic 校验)
- Uvicorn (ASGI 服务器)
- Docker 容器化

**前端**:
- React 19 + TypeScript 5
- Vite 5
- Monaco Editor (代码编辑器)
- TanStack Query (数据请求与缓存)

**Worker**:
- 5 种语言独立进程,通过 stdio JSON-RPC 与 API 层通信。
- C/C++ 用 PyClang (libclang 绑定)。
- Python 用标准库 `ast`。
- Java 用 JavaParser CLI (subprocess)。
- Go 用 go ast CLI (subprocess)。

## 支持的 OJ 预设

| OJ | 预设名 | 强度 | 策略组合 |
|---|---|---|---|
| Codeforces | `cf-strict` | 弱 | 标识符改名 + 简单控制流平坦化 |
| AtCoder | `atcoder-strict` | 弱 | 同上,无垃圾代码 |
| 牛客 | `nowcoder-mid` | 中 | 改名 + 控制流改写 + 局部表达式拆分 |
| PTA | `pta-strong` | 强 | 改名 + 控制流改写 + 表达式拆分 + 垃圾代码 + 函数拆分 |
| 学习通 | `xuexitong-strong` | 强 | 同 PTA,且模板参数随机化 |

## 安全与隐私

- **不存储用户代码**:代码仅在请求生命周期存在,不写盘,日志不含代码内容。
- **沙箱**:Worker 进程以低权限运行,禁外网,禁文件系统写(除 `/tmp` 临时文件)。
- **速率限制**:单 IP 并发 2,单请求 ≤ 200KB。
- **CSP**:前端禁 inline script / 外链脚本。

## 禁止用途

- 学术不端 / 作业抄袭 / 比赛代打。
- 商业代码保护(本服务对上传代码无保密能力)。
- 任何违反目标 OJ 服务条款的用途。

## 合规

页面底部固定"勿用于学术不端"提示,首次访问弹窗提示。

**MVP 阶段**:无用户协议 / 隐私政策 / 退订机制。
**上线后**(M5):补全用户协议、隐私政策、注销账户、发票、退款等合规条款(详见 SPEC §15)。

## License

MIT License —— 详见 [LICENSE](LICENSE) 文件。

## 贡献指南

**当前阶段**:暂不接受外部 PR,项目处于 MVP 开发期。

**后续开放贡献时**:
- 所有新功能先在 SPEC.md 提案,讨论后再实现。
- 所有代码需通过 ruff / prettier 格式化 + pytest / vitest 测试。
- 安全漏洞请通过 GitHub Security Advisory 报告。

## 联系

- 问题反馈:GitHub Issues
- 邮件:(留空,后续补充)

---

> 本项目参考了 [CodeConfuseTool](https://github.com/anthropic/CodeConfuseTool) (桌面版)的混淆思路,但完全重写为 Web 版本,采用 AST 级别变换。
