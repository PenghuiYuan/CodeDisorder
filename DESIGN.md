# CodeConfuse.Web —— 设计文档(DESIGN)

> 本文档是 SPEC.md 的下一层。**读者:实现者本人(你)**。**粒度:到文件:函数级别**。
> 你应当能照着这份文档写代码,不需要再做一次设计决策。
> SPEC 说了"做什么 / 不做什么",本文档说"怎么做 / 改哪个文件 / 调哪个 API"。

---

## 0. 本文档与 SPEC.md 的关系

### 0.1 不复述的章节(直接看 SPEC)

- §0 已确认事项 / §1 背景目标 / §2 用户场景 / §3 范围 / §4 总体架构图
- §9 安全与合规 / §10 风险 / §11 里程碑 / §12 验收 / §14 UI 规范
- §15 上线扩展点

### 0.2 在本文档里展开的章节(SPEC 没定死,这里定)

| SPEC 章节 | 本文展开 |
|---|---|
| §3.1 支持语言 | §3 / §4 / §5 / §6 各语言适配层 |
| §3.2 OJ 预设 | §3.4 `presets.json` 格式 |
| §3.3 混淆策略 | §4 / §5 / §6 各策略的具体 AST 操作 |
| §5 关键流程 | §3.3 JSON-RPC 协议、§8 并行调度、§9 验证 |
| §6 接口 | §3.2 FastAPI 路由、§10.1 错误码 |
| §7 资源 | §7 词表与不透明谓词库 |
| §11 里程碑 | §11 每日 todo |

### 0.3 技术选型(SPEC 没定,这里定)

| 维度 | 选择 | 原因 |
|---|---|---|
| 后端语言 | Python 3.11+ | 你已确认;`ast` 1 行;PyClang 是 libclang 官方绑定 |
| 后端框架 | FastAPI 0.110+ | 异步、原生 OpenAPI、Pydantic 校验与 SPEC §6.1 schema 一致 |
| ASGI 服务器 | Uvicorn | FastAPI 标准搭配 |
| 进程通信 | stdio JSON-RPC | API 层与 Worker 解耦,无外部依赖,gRPC 太重 |
| 容器化 | Docker + docker-compose | SPEC §4.3 要求可水平扩缩 |
| 任务调度 | 内置 asyncio.Queue(单节点) / Redis(多节点) | MVP 单节点,M3 决定是否上 Redis |
| 前端构建 | Vite 5 | 你已确认 |
| 前端框架 | React 19 + TypeScript 5 | 你已确认 |
| Monaco 封装 | `@monaco-editor/react` | 官方推荐 |
| HTTP 客户端 | fetch + TanStack Query | 缓存 / 状态管理 |
| 测试 | pytest(后端) + vitest(前端) | 标准 |
| 格式化 | ruff(后端) + prettier(前端) | 工具最少 |

---

## 1. 仓库结构

单仓,后端 + 前端 + 资源都在一起。

```
code_confuse_web/
├── README.md                  # 一句话启动: docker-compose up
├── SPEC.md                    # 需求(已存在)
├── DESIGN.md                  # 本文件
├── pyproject.toml             # Python 依赖与 ruff 配置
├── package.json               # 前端依赖
├── docker-compose.yml         # 一键启动(api + web)
├── .env.example
├── backend/
│   ├── api/                   # FastAPI 入口
│   │   ├── main.py
│   │   ├── routes_confuse.py
│   │   ├── routes_meta.py     # /api/presets, /api/strategies, /api/health
│   │   ├── schemas.py         # Pydantic 模型(对齐 SPEC §6.1)
│   │   ├── errors.py          # 错误码定义(对齐 SPEC §15.6)
│   │   ├── dispatcher.py      # 把请求路由到对应 Worker
│   │   └── worker_client.py   # stdio JSON-RPC 客户端
│   ├── workers/               # 5 种语言 × 独立进程
│   │   ├── common/
│   │   │   ├── jsonrpc.py     # 行分隔 JSON-RPC over stdio
│   │   │   ├── runner.py      # worker 入口模板
│   │   │   └── seed.py        # 种子化随机
│   │   ├── c_cpp/             # libclang(PyClang)
│   │   │   ├── worker.py
│   │   │   ├── transformer.py
│   │   │   ├── rewriter.py
│   │   │   └── strategy_*.py  # 每个策略一个文件
│   │   ├── python/            # ast
│   │   ├── java/              # subprocess 调 javaparser-cli
│   │   ├── go/                # subprocess 调 go_ast_tool
│   │   └── lang_template/     # 新语言 Worker 脚手架
│   ├── verify/                # 验证子进程封装
│   │   ├── gcc.py
│   │   ├── clang.py
│   │   ├── javac.py
│   │   ├── go_vet.py
│   │   └── python_ast.py
│   ├── resources/             # 只读资源(SET 打包到容器)
│   │   ├── wordlist.txt
│   │   ├── opaque_predicates.json
│   │   ├── language_settings/
│   │   │   ├── cpp.json
│   │   │   ├── c.json
│   │   │   ├── python.json
│   │   │   ├── java.json
│   │   │   └── go.json
│   │   ├── presets.json       # 5 个 OJ 预设 + 1 个 custom
│   │   └── templates/
│   │       └── ...            # 兜底代码模板(预留,MVP 可空)
│   ├── tools/                 # 一次性脚本
│   │   └── gen_wordlist.py    # 从系统词典生成 wordlist.txt
│   └── tests/
│       ├── fixtures/          # 5 种语言各 10~20 个 OJ 真题
│       ├── test_api.py
│       ├── test_workers_cpp.py
│       ├── test_workers_python.py
│       └── test_dispatcher.py
└── frontend/
    ├── index.html
    ├── vite.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── components/
    │   │   ├── EditorPanel.tsx
    │   │   ├── ControlBar.tsx
    │   │   ├── ResultPanel.tsx
    │   │   ├── PresetSelect.tsx
    │   │   ├── CountSelect.tsx
    │   │   └── StrategyCustomizer.tsx
    │   ├── hooks/
    │   │   ├── useConfuse.ts
    │   │   └── useMeta.ts     # 拉 /api/presets, /api/strategies
    │   ├── lib/
    │   │   ├── api.ts
    │   │   └── download.ts
    │   └── styles/
    │   └── pages/             # 留空,当前只有单页
    └── tests/
```

**关键约定**:
- 任何"业务逻辑"只放 `backend/`,前端不做规则判断。
- 每个语言 Worker 是一份**独立可执行的 Python 脚本**(`python -m backend.workers.c_cpp.worker`),通过 stdio 接收 JSON-RPC,保证隔离。
- `resources/` 整个目录在容器构建时 `COPY`,运行时只读。

---

## 2. M0:从 CodeConfuseTool 桌面版到 Web 的迁移

> 一次性任务,迁移完即结束。目标是"用我们已有 Qt 工具的思路,重新实现一遍到 Web"。

### 2.1 复用的部分(直接搬到 Web)

| 桌面版 | Web 复用 |
|---|---|
| `CodeConfusing/dict.txt` | `backend/resources/wordlist.txt`(原样拷贝,但去 BOM) |
| `CodeConfusing/reskeys.txt` | `backend/resources/language_settings/<lang>.json::reserved` |
| `CodeConfusing/codepiece.json` | `backend/resources/templates/c_cpp/garbage.json`(MVP 仅 C/C++ 用) |
| `ResultDialog` 思路 | 改成"生成源码 + 返回 JSON" |

### 2.2 不复用的部分(完全重写)

| 桌面版 | 不复用原因 |
|---|---|
| `cppparser.cpp` 整套 | SPEC §1 要求 AST 级别;桌面版是文本状态机,误差大 |
| `ocparser.cpp` | 不在 MVP 范围 |
| `mainwindow.cpp` 整套 UI | SPEC §14 全新的翻译器式 UI |
| `garbagecode.cpp` 的"上一行 ) + 下一行 {"启发式 | 太脆,SPEC §3.3 改成 AST 级别垃圾代码 |
| `database.cpp` 的 `m_identifyVec` / `m_modelVec` | 改用 Worker 内部的数据结构,不再用单例 |

### 2.3 一次性迁移脚本

`backend/tools/migrate_from_qt.py`:
- 读 `CodeConfuseTool/CodeConfusing/dict.txt`,写 `backend/resources/wordlist.txt`,去 BOM + 排序。
- 读 `CodeConfuseTool/CodeConfusing/reskeys.txt`,按语言分类(简单启发式:含 `__attribute__` → c/cpp,含 `def` → python 等),写 `language_settings/*.json::reserved`。
- 读 `CodeConfuseTool/CodeConfusing/codepiece.json`,改名为 `templates/c_cpp/garbage.json`,加语言字段。

完成后,桌面版代码**完全不再被 Web 引用**;你可��保留作为对比参考,或删除。

---

## 3. 后端 Worker 进程设计

### 3.1 进程模型

```
[ FastAPI 进程 ]
     │  HTTP /api/confuse
     ▼
[ Dispatcher ]
     │  启动或复用 Worker 子进程
     ▼
[ Worker 进程 (stdio JSON-RPC) ]
     │  parse / transform / verify
     ▼
[ 返回 JSON-RPC 响应 ]
```

- **每个 Worker 进程只服务一种语言**。Dispatcher 维护 "语言 → 进程 PID" 的池。
- **MVP 阶段每种语言 1 个进程**,M3 决定是否每种语言起 2~4 个进程并行。
- Worker 进程**长驻**,通过 stdio 与 API 层通信;空闲时阻塞读 stdin,需要时收到 JSON-RPC 请求,处理完返回响应再阻塞。

### 3.2 FastAPI 路由(`backend/api/routes_confuse.py`)

```python
# 文件:backend/api/routes_confuse.py
# 函数签名:

async def confuse(req: ConfuseRequest) -> ConfuseResponse:
    """对应 SPEC §6.1 POST /api/confuse"""

# 内部流程(伪代码):
# 1. 校验 req.language_in == req.language_out → 否则 400,code=invalid_target_language
# 2. 校验 req.count in {1, 3, 5, 10} → 否则 400,code=invalid_count
# 3. 校验 len(req.code.encode('utf-8')) <= 200 * 1024 → 否则 413,code=payload_too_large
# 4. worker = dispatcher.acquire(req.language_in)
# 5. try:
#       result = await worker_client.call(worker, "confuse", req.dict(), timeout=10.0)
#    except WorkerTimeoutError:
#       # 降级一次:重发,不带 flatten/junk
#       result = await worker_client.call(worker, "confuse", req.dict(without_aggressive=True), timeout=5.0)
#    finally:
#       dispatcher.release(worker)
# 6. 把 result 转成 ConfuseResponse 返回
```

### 3.3 Worker stdio JSON-RPC 协议(`backend/workers/common/jsonrpc.py`)

**消息格式**(每行一个 JSON,行分隔):

```json
// 请求
{"jsonrpc": "2.0", "id": 1, "method": "confuse", "params": {...}}

// 成功响应
{"jsonrpc": "2.0", "id": 1, "result": {...}}

// 失败响应(协议级)
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}

// 通知(Worker 主动上报,无 id)
{"jsonrpc": "2.0", "method": "progress", "params": {"stage": "transform", "pct": 50}}
```

**API 层 → Worker 的方法**:
- `confuse(params)`:主入口,params 同 SPEC §6.1 请求体,返回 `{code, applied, verify, failed_indexes?}`。
- `ping()`:健康检查,API 层启动时调用一次。
- `shutdown()`:优雅退出,API 层关闭时调用。

**Worker → API 层的通知**:
- `progress(stage, pct)`:批量生成时,每完成一个变体上报一次,API 层用 SSE 推给前端(MVP 阶段可以忽略,前端用 polling 即可)。

**实现要点**:
- 用 `asyncio.create_subprocess_exec` 启动 Worker,stdin/stdout 配 `PIPE`。
- API 层维护 `dict[int, WorkerHandle]`,id 用 `uuid4().int` 生成。
- 读 stdout 用 `asyncio.StreamReader.readline()`,逐行 `json.loads`。
- 超时:`asyncio.wait_for(worker_client.call(...), timeout=10)`。

### 3.4 OJ 预设定义(`backend/resources/presets.json`)

```json
{
  "presets": [
    {
      "id": "cf-strict",
      "display": "Codeforces",
      "strength": "weak",
      "strategies": {
        "rename": true,
        "flatten": "simple",
        "junk": false,
        "splitExpression": false,
        "splitFunction": false,
        "templateRandom": false,
        "stripComments": true,
        "shuffleIncludes": true
      }
    },
    {
      "id": "pta-strong",
      "display": "PTA / 教学型 OJ",
      "strength": "strong",
      "strategies": {
        "rename": true,
        "flatten": "deep",
        "junk": "aggressive",
        "splitExpression": true,
        "splitFunction": true,
        "templateRandom": true,
        "stripComments": true,
        "shuffleIncludes": true
      }
    }
  ],
  "custom": {
    "display": "自定义",
    "strategies": { /* 全 false,UI 让用户勾选 */ }
  }
}
```

`strategies` 字段对应 SPEC §3.3 的 S1~S9。`"deep"` / `"aggressive"` 等枚举值由各语言 Worker 自行解释。

加载函数:`backend/api/routes_meta.py::load_presets() -> dict`,启动时一次性 `json.load` 到内存,后续只读。

### 3.5 Dispatcher(`backend/api/dispatcher.py`)

```python
class WorkerHandle:
    pid: int
    language: str
    process: asyncio.subprocess.Process
    busy: bool
    last_used: float

class Dispatcher:
    _pools: dict[str, list[WorkerHandle]]  # language -> [handles]

    async def acquire(self, language: str, timeout: float = 30.0) -> WorkerHandle:
        """取一个空闲 Worker,没有就启动新进程,池满则等待"""

    def release(self, handle: WorkerHandle) -> None:
        """归还,空闲超 60s 则 kill 进程(防止内存泄漏)"""
```

**MVP 阶段**:`_pools` 每种语言最多 1 个进程;`acquire` 拿不到就 `asyncio.sleep(0.1)` 轮询;`release` 时不主动 kill,留给 60s 后台任务(M2 实现)。

---

## 4. libclang 适配层(替代 cppparser.cpp)

> 这是 MVP 后端最复杂的一块,本节**最细**。

### 4.1 入口

`backend/workers/c_cpp/worker.py`:

```python
# 文件:backend/workers/c_cpp/worker.py
def main():
    """Worker 入口,运行在独立进程中"""
    from backend.workers.common.jsonrpc import serve
    from backend.workers.c_cpp.transformer import ConfuseTransformer
    serve(
        handlers={
            "ping": lambda _: {"ok": True},
            "confuse": ConfuseTransformer().handle,
            "shutdown": lambda _: (_ for _ in ()).throw(SystemExit),
        }
    )
```

`ConfuseTransformer` 是核心类,所有策略都挂在它上面。

### 4.2 解析层:从源码到 libclang AST

```python
# 文件:backend/workers/c_cpp/transformer.py
import clang.cindex

class ConfuseTransformer:
    def handle(self, params: dict) -> dict:
        code = params["code"]
        language = params["language_in"]  # "c" or "cpp"
        preset_id = params["preset"]
        count = params.get("count", 1)
        overrides = params.get("overrides", {})

        # 1. 预清洗
        clean_code = self._preclean(code)

        # 2. 解析
        index = clang.cindex.Index.create()
        # 用 unsaved_files 把字符串喂进去,避免写盘
        tu = index.parse(
            "input.{}".format("cpp" if language == "cpp" else "c"),
            unsaved_files=[("input.{}".format(language), clean_code)],
            args=["-std=c++17" if language == "cpp" else "-std=c11",
                  "-fsyntax-only", "-w"],
        )
        if tu.diagnostics:
            errors = [{"line": d.location.line, "column": d.location.column,
                       "message": d.spelling} for d in tu.diagnostics
                      if d.severity >= clang.cindex.Diagnostic.Error]
            if errors:
                return self._err("parse_error", "parse", errors)

        # 3. 选择策略
        strategies = self._select_strategies(preset_id, overrides)

        # 4. 变换
        results = []
        for i in range(count):
            seed = self._seed_for(params, i)
            transformed = self._transform(tu, strategies, seed)
            results.append(transformed)

        # 5. 验证(单文件 count=1 时必跑,count>1 时可选)
        if count == 1:
            verify = self._verify(results[0], language)
            return self._ok(results, strategies, verify)

        # 批量:每个变体独立验证,失败的剔除
        ok_results, failed = [], []
        for i, r in enumerate(results):
            if self._verify(r, language)["status"] == "ok":
                ok_results.append(r)
            else:
                failed.append(i + 1)
        return self._ok_batch(ok_results, strategies, failed)
```

**关键点**:
- `index.parse(..., unsaved_files=...)`:避免任何写盘,符合 SPEC §7.1 "不写盘"。
- `diagnostics` 包含所有错误,过滤出 `Error` 级别作为解析错误返回。
- 每个变体用**独立种子**:`_seed_for(params, i)`,保证同一份代码 + 同一 OJ 预设 + 同一 `i` 在不同时间产出**一致**(SPEC §10 风险:可复现性)。

### 4.3 策略应用:`_transform` 函数签名

```python
def _transform(self, tu: clang.cindex.TranslationUnit,
               strategies: dict, seed: int) -> str:
    """
    返回混淆后源码字符串。
    策略按 SPEC §3.3 顺序应用:S8(预清洗已在 step1) → S9 → S1 → S2 → S5 → S3 → S4 → S6 → S7
    """
```

**实现策略的最小子集**(MVP 必做):

| 策略 | 函数 | 关键 API |
|---|---|---|
| S1 改名 | `_apply_rename(tu, mapping, seed) -> str` | 走 `Rewriter` 替换 `Cursor.extent` 范围内的 token |
| S2 数字字面量 | `_apply_literal_rewrite(tu, seed) -> str` | 遍历 `Cursor.kind == CursorKind.INTEGER_LITERAL` 等,改成等价表达式(如 `5` → `0x5`,或 `5` → `(2 + 3)`) |
| S3 控制流平坦化 | `_apply_flatten(tu, depth: str) -> str` | 对 `FunctionDecl` 内的 `CompoundStmt` 拆成 `switch(state) { case 0: ...; state = 5; break; ... }` |
| S4 死代码 | `_apply_junk(tu, level: str) -> str` | 在 `if` 条件为"不透明谓词"(如 `((x*x+1) % 2 == 1)`)时插入空块 |
| S5 表达式拆分 | `_apply_split_expr(tu, seed) -> str` | 对 `BinaryOperator`(`+ - * /`)插入中间变量 |
| S6 函数拆分 | `_apply_split_function(tu, seed) -> str` | 把超过 N 行的 `FunctionDecl` 切成几个 `static` 子函数 |
| S7 模板参数 | `_apply_template_random(tu, seed) -> str` | 对 `TemplateTypeParmDecl` 重新生成一个等价的占位符 |
| S8 注释剥离 | (在 `_preclean` 里) | libclang 本身会忽略注释,但 `R"..."` 字符串里可能有 `//`,用 regex 提前剥 |
| S9 include 随机 | `_apply_shuffle_includes(tu, seed) -> str` | 收集 `CursorKind.INCLUSION_DIRECTIVE`,随机打乱顺序 |

**MVP 范围**(按 SPEC §3.4):S1、S2、S3(单层)、S4(简单)、S5(限二元)、S8、S9 必做;S6、S7 留接口不实现(返回原 AST 不变)。

### 4.4 改名映射生成(`_gen_rename_mapping`)

```python
def _gen_rename_mapping(self, tu, seed: int) -> dict[str, str]:
    """
    收集所有需要改名的 Cursor,生成原名 → 新名映射。
    返回 dict,key 是原 identifier 字符串,value 是新名字。
    """
    rng = random.Random(seed)
    used = set(self._reserved_keywords(language))  # 保留字表
    new_names = set()

    cursors = []
    tu.cursor.walk_preorder(lambda c, _: cursors.append(c) or True
                             if c.kind in (CursorKind.VAR_DECL, CursorKind.FUNCTION_DECL,
                                           CursorKind.CXX_METHOD, CursorKind.FIELD_DECL,
                                           CursorKind.PARM_DECL, CursorKind.CXX_RECORD)
                             else None)

    for c in cursors:
        spelling = c.spelling
        if not spelling or not self._is_user_symbol(spelling):
            continue
        # 从词表抽一个未占用的
        new = self._pick_from_wordlist(rng, used | new_names)
        new_names.add(new)
        mapping[spelling] = new
    return mapping
```

**关键**:
- 用 PyClang 的 `walk_preorder` 走 AST,比桌面版 `divideByTab` 切字符串稳得多。
- `_is_user_symbol` 检查"不是系统头里的符号",通过 `Cursor.location.file.name == "input.c"` 判断(MVP 阶段,只要不是 `<built-in>` / `__PRETTY_FUNCTION__` 等就算用户符号)。
- `_pick_from_wordlist` 从 `wordlist.txt` 抽词,首字母匹配原名大小写风格(原名 `PascalCase` → 新名 `PascalCase`,`snake_case` → `snake_case`)。

### 4.5 代码生成:`_emit_code`

```python
def _emit_code(self, tu: clang.cindex.TranslationUnit) -> str:
    """
    从 TranslationUnit 输出源码。
    MVP 策略:不动 AST 节点,只在 SourceRange 上做字符串替换。
    """
    # 用 libclang 的 Token 列表 + Rewriter API
    rewriter = clang.cindex.Rewriter.create(tu)
    # ... 应用所有 SourceRange 替换 ...
    return rewriter.getRewrittenText()
```

> PyClang 的 `Rewriter` API 不完整,实测可能只支持 `InsertTextBefore` / `ReplaceText` / `RemoveText`。MVP 阶段如果 Rewriter 不够用,**退回到"Token + 偏移拼接"**:用 `tu.get_tokens(extent)` 拿到所有 token,记录每个要改的 token 的偏移,在原始字符串上 `splice`。

**这是最容易踩坑的地方**,需要实际跑一遍 PyClang 才知道具体 API。**todo**:`backend/tests/test_cpp_rewrite.py` 必须有集成测试。

### 4.6 预清洗:`_preclean`

```python
def _preclean(self, code: str) -> str:
    # 1. 去 BOM
    if code.startswith("\ufeff"):
        code = code[1:]
    # 2. 统一换行
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    # 3. 剥注释(防字符串里出现 // 误判,S8 提前做)
    code = self._strip_comments_safe(code)
    return code

def _strip_comments_safe(self, code: str) -> str:
    """
    状态机:识别 /* */、//、字符串字面量("...")、字符字面量('...')、原始字符串 R"(...)"。
    字符串/字符/原始字符串里的 // 不删。
    """
    # 见 §4.7 共享 lexer 状态机
```

### 4.7 共享 lexer 状态机

`backend/workers/common/lexer.py`(5 种语言 Worker 共用):

```python
def strip_comments_and_track_spans(code: str) -> tuple[str, list[tuple[int, int, str]]]:
    """
    返回 (清洗后代码, span 列表)。
    span 元素: (原始偏移, 清洗后偏移, 类型) 类型 ∈ {"comment", "string"}.
    用于后续把"清洗后代码"的 token 偏移映射回"原始代码"的偏移。
    """
```

这个状态机**5 种语言都需要**(C/C++/Java/Go 的字符串字面量语法相似;Python 加三引号)。**用单个状态机写一次,所有 Worker 复用**。

状态:`NORMAL / IN_LINE_COMMENT / IN_BLOCK_COMMENT / IN_STRING / IN_CHAR / IN_RAW_STRING`,转换表写死;对 Python 额外加 `IN_TRIPLE_STRING` 状态。

---

## 5. Python ast 适配层

### 5.1 入口

`backend/workers/python/worker.py` 结构与 c_cpp 几乎一致,只是 `transformer.py` 改用 `ast`。

### 5.2 解析与变换

```python
# 文件:backend/workers/python/transformer.py
import ast

class ConfuseTransformer:
    def handle(self, params: dict) -> dict:
        code = params["code"]
        try:
            tree = ast.parse(code, type_comments=True)
        except SyntaxError as e:
            return self._err("parse_error", "parse", [{
                "line": e.lineno, "column": e.offset, "message": e.msg
            }])

        strategies = self._select_strategies(...)
        seed = self._seed_for(params, 0)

        # Python 用 node transformer / node visitor
        for strat in strategies:
            transformer = STRATEGIES[strat](seed)
            tree = transformer.visit(tree)
            ast.fix_missing_locations(tree)

        # 反生成代码:用 ast.unparse (Python 3.9+)
        try:
            new_code = ast.unparse(tree)
        except Exception as e:
            return self._err("transform_error", "transform", ...)

        # 验证
        verify = self._verify(new_code)
        return self._ok(new_code, strategies, verify)
```

### 5.3 Python 特有的策略实现

| 策略 | 实现 |
|---|---|
| S1 改名 | `ast.NodeTransformer`,遍历 `ast.Name` / `ast.FunctionDef` / `ast.ClassDef` / `ast.arg`,按名字映射替换。**注意**:不能改 `self` / `cls` / 关键字。 |
| S2 数字 | `ast.Constant(value=int|float)`,改成等价的 `ast.BinOp`(`5` → `ast.BinOp(2, Add, 3)`)。 |
| S3 控制流平坦化 | 对 `ast.If` / `ast.For` / `ast.While` 用 `while True: switch(state) ...` 模式(MVP 不做,Python 改 CFG 收益小)。 |
| S4 死代码 | 在 `ast.If.test` 注入 `and (lambda x: x*x + 1)(0) % 2 == 1`(永真)。 |
| S5 表达式拆�� | `BinOp` 拆成 `tmp1 = a; tmp2 = b; result = tmp1 op tmp2`,通过插 `ast.Assign`。 |
| S8 / S9 | import 顺序随机:`ast.Module.body` 里 `Import` / `ImportFrom` 节点随机打乱。 |

**MVP 必做**:S1、S2、S5、S8、S9。S3、S4 留接口。

### 5.4 验证子进程

```python
def _verify(self, code: str) -> dict:
    """Python 验证只需 ast.parse 再解析一次"""
    try:
        ast.parse(code)
        return {"status": "ok", "level": "syntax-ok"}
    except SyntaxError as e:
        return {"status": "error", "level": "syntax-err", "message": str(e)}
```

不需要起子进程,直接 `ast.parse` 即可。

---

## 6. JavaParser / go ast 适配层(MVP 接口预留)

### 6.1 Java(M2 实现,MVP 留接口)

不在 MVP 范围,但骨架要搭好:

`backend/workers/java/worker.py`:

```python
def handle(self, params):
    # 1. 把 code 写到临时文件
    with tempfile.NamedTemporaryFile(suffix=".java", mode="w", delete=False) as f:
        f.write(params["code"])
        src = f.name
    # 2. subprocess 调 java -jar javaparser-cli.jar transform < src > dst
    proc = subprocess.run(
        ["java", "-jar", "/opt/javaparser-cli.jar", "transform", "--preset", params["preset"]],
        input=open(src).read(), capture_output=True, text=True, timeout=5
    )
    if proc.returncode != 0:
        return self._err(...)
    # 3. 验证:javac 编译
    verify = self._javac_verify(proc.stdout, src.replace(".java", "Confused.java"))
    return self._ok(proc.stdout, ...)
```

`javaparser-cli.jar` 是一个**单独的 Java 小工具**,代码在 `backend/tools/javaparser-cli/`,用 JavaParser 库实现 parse + transform + emit,通过 stdin/stdout 与 Python 通信。M2 时实现。

### 6.2 Go(M2 实现,MVP 留接口)

同模式:`backend/tools/go_ast_tool/` 写一个 Go 小程序,接收 stdin 上的 Go 源码,输出混淆后源码。Python Worker 走 subprocess。

MVP 阶段,Java / Go Worker 启动时直接返回 `{"status": "error", "code": "language_not_supported", ...}`,前端按 SPEC §14.6 显示"该语言暂未上线"。

---

## 7. 词表与不透明谓词库

### 7.1 词表生成

`backend/tools/gen_wordlist.py`:

```python
# 从 /usr/share/dict/words(Linux / macOS 都自带)抽取:
# 1. 长度 >= 4 且 <= 12(避免过短撞变量,过长难读)
# 2. 全 ASCII 字母
# 3. 去重 + 排序
# 4. 输出 backend/resources/wordlist.txt
```

词表规模目标:30,000~50,000 词(SPEC §7.2 说 ~3MB,实测这个规模合适)。从 `dict.txt` 已有 21 万词里再过一道筛。

### 7.2 不透明谓词库

`backend/resources/opaque_predicates.json`:

```json
{
  "predicates": [
    {
      "id": "x*x_plus_1_odd",
      "languages": ["c", "cpp", "java", "go"],
      "template": "(({x}*{x}+1) % 2 == 1)",
      "value": true,
      "note": "x*x is even, +1 is odd"
    },
    {
      "id": "x_squared_nonneg",
      "languages": ["c", "cpp", "java", "go"],
      "template": "(({x}*{x}) >= 0)",
      "value": true
    },
    {
      "id": "seven_div_three_two",
      "languages": ["c", "cpp", "java", "go", "python"],
      "template": "((7/3) == 2)",
      "value": true
    }
  ]
}
```

- `id`:唯一标识。
- `languages`:适用语言。
- `template`:`{x}` 是占位符,运行时被替换成一个不冲突的变量名(如 `_opq1`)。
- `value`:编译期 / 解释期恒为真(`true`)或恒为假(`false`),Worker 在 `if` / `while` 注入时根据 `value` 选分支。
- MVP 库:5~10 个谓词够用。

### 7.3 词表与映射的内存格式

`backend/workers/common/wordlist.py`:

```python
class WordList:
    _words: list[str]
    _by_style: dict[str, list[str]]  # "pascal" / "snake" / "camel" -> [words]

    @classmethod
    def load(cls, path: str = "backend/resources/wordlist.txt") -> "WordList":
        # mmap 读,一次性转 list
        # 预按"首字母大写 / 全小写 / camelCase"分组
```

启动时一次性加载(词表 3MB,加载 < 100ms),运行期 O(1) 抽词。

---

## 8. 批量生成(count > 1)与并行调度

### 8.1 并行模型

`count = 1`:Worker 单进程顺序处理。
`count > 1`:**单 Worker 进程顺序处理 N 个变体**(每个变体独立种子,变换 + 验证循环 N 次)。

**为什么不上多 Worker 并行**:MVP 阶段每种语言 1 个进程足够(SPEC §8.1 性能:count=10 P95 < 25s,串行 10 个变体 < 25s 合理)。M3 再考虑多进程。

### 8.2 种子生成(`_seed_for`)

```python
def _seed_for(self, params: dict, variant_idx: int) -> int:
    """
    保证:同一份代码 + 同一 OJ 预设 + 同一 variant_idx 在不同时间产生同一结果。
    """
    import hashlib
    h = hashlib.sha256()
    h.update(params["code"].encode("utf-8"))
    h.update(b"|")
    h.update(params["preset"].encode("utf-8"))
    h.update(b"|")
    h.update(variant_idx.to_bytes(4, "big"))
    digest = h.digest()
    return int.from_bytes(digest[:8], "big")
```

满足 SPEC §10 风险对策"可复现"。

### 8.3 并行调度的失败处理

`count > 1` 时,某几个变体验证失败不致命:
- 收集 `failed_indexes`(从 1 开始);
- zip 里只放成功的;
- 全失败时返回 `code=verify_error`,HTTP 200(不是 500),让前端显示"5 个全部失败"。

---

## 9. 验证层

### 9.1 C/C++:gcc / clang 编译验证

`backend/verify/gcc.py` / `backend/verify/clang.py`:

```python
def verify_cpp(code: str, language: str) -> dict:
    """
    编译验证,不链接。
    language: "c" or "cpp"
    返回: {"status": "ok"|"error", "level": "compiled"|"warning", "errors": [...]}
    """
    suffix = ".cpp" if language == "cpp" else ".c"
    std = "c++17" if language == "cpp" else "c11"
    compiler = "g++" if language == "cpp" else "gcc"

    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(code)
        src_path = f.name
    try:
        proc = subprocess.run(
            [compiler, "-std=" + std, "-fsyntax-only", "-w", src_path],
            capture_output=True, text=True, timeout=5
        )
        if proc.returncode == 0:
            return {"status": "ok", "level": "compiled"}
        # 解析 stderr,提取 line:col 错误
        errors = _parse_gcc_stderr(proc.stderr)
        return {"status": "error", "level": "verify", "errors": errors}
    except subprocess.TimeoutExpired:
        return {"status": "error", "level": "timeout"}
    finally:
        os.unlink(src_path)
```

### 9.2 资源限制(SPEC §9)

Worker 子进程层(不是验证子进程层)用容器 cgroup;验证子进程层用 `subprocess.run(timeout=5)` 已经够。**不引入** seccomp / Landlock(SPEC §13.17 留作 M3+)。

**todo**:`docker-compose.yml` 给 Worker 容器设:

```yaml
deploy:
  resources:
    limits:
      cpus: "1.0"
      memory: 512M
```

### 9.3 验证子进程临时文件清理

每个 verify 调 `tempfile.NamedTemporaryFile(delete=False)`,用完 `os.unlink`。`try/finally` 保证异常也清。

如果验证超时,临时文件可能残留;`backend/verify/_cleanup.py` 启动时 `glob.glob("/tmp/tmp*.cpp")` 清一遍(简单粗暴,MVP 可用)。

---

## 10. 错误响应码与降级策略

### 10.1 错误码定义(`backend/api/errors.py`)

```python
from enum import Enum

class ErrorCode(str, Enum):
    # 对应 SPEC §15.6
    PARSE_ERROR         = "parse_error"
    VERIFY_ERROR        = "verify_error"
    TRANSFORM_ERROR     = "transform_error"
    QUOTA_EXCEEDED      = "quota_exceeded"        # MVP 不用,留位
    AUTH_REQUIRED       = "auth_required"         # MVP 不用,留位
    AUTH_INVALID        = "auth_invalid"          # MVP 不用,留位
    SUBSCRIPTION_EXPIRED= "subscription_expired"  # MVP 不用,留位
    PAYMENT_REQUIRED    = "payment_required"      # MVP 不用,留位
    RATE_LIMITED        = "rate_limited"
    PAYLOAD_TOO_LARGE   = "payload_too_large"
    INTERNAL_ERROR      = "internal_error"
    # MVP 新增:
    INVALID_TARGET_LANGUAGE = "invalid_target_language"
    INVALID_COUNT           = "invalid_count"
    LANGUAGE_NOT_SUPPORTED  = "language_not_supported"
```

每个错误响应统一格式(SPEC §6.1 失败响应):

```python
def error_response(code: ErrorCode, stage: str, message: str, errors: list = None):
    return {
        "status": "error",
        "code": code.value,
        "stage": stage,
        "message": message,
        "errors": errors or [],
    }
```

### 10.2 降级状态机(SPEC §5.3)

`backend/api/routes_confuse.py` 内:

```python
# 三档降级,对应 SPEC §13.18:
# L0: 全策略(S1~S9)
# L1: 去 S4(死代码)
# L2: 去 S3(控制流改写)
# L3: 仅 S1(改名) + S8/S9
# L4: 直接报错

async def confuse_with_fallback(params):
    for level in [L0, L1, L2, L3]:
        try:
            result = await try_confuse(params, level)
            if result["verify"]["status"] == "ok":
                if level != L0:
                    result["degraded_from"] = "L0"
                return result
        except WorkerTimeoutError:
            continue
    return error_response(ErrorCode.VERIFY_ERROR, "verify", "已穷尽降级,无法通过验证")
```

`level` 的实际策略开关是一个 `dict[str, bool]`,传给 Worker;Worker 按 §3.4 的 strategies 字段应用。

---

## 11. M1 周计划(可执行的每日 todo)

> 总目标:SPEC §12 M1 验收标准全过。
> 周期:5 周(M1 + M2 + M3 各占一部分,本节只列 M1 的 3 周)。

### 第 1 周(基础设施)

- [ ] **周一**
  - [ ] 初始化仓库结构(§1)
  - [ ] `pyproject.toml` 写好:fastapi / uvicorn / pyclang / ruff / pytest
  - [ ] `package.json` 写好:react 19 / vite 5 / @monaco-editor/react / tanstack-query
  - [ ] `docker-compose.yml` 写好(api + web 两个 service)
- [ ] **周二**
  - [ ] `backend/workers/common/jsonrpc.py::serve(handlers)` 实现并写单测
  - [ ] `backend/workers/common/lexer.py::strip_comments_and_track_spans` 实现并写单测(5 种语言的字符串/注释 case)
  - [ ] `backend/workers/common/wordlist.py::WordList.load` 实现
- [ ] **周三**
  - [ ] `backend/tools/migrate_from_qt.py` 写好,跑一次,把 `CodeConfuseTool/CodeConfusing/{dict,reskeys,codepiece}.*` 迁过来
  - [ ] `backend/tools/gen_wordlist.py` 写好,跑一次,产出 `wordlist.txt`
  - [ ] `backend/api/main.py` + `routes_meta.py`(只实现 `/api/health`, `/api/presets`, `/api/strategies`)+ `resources/presets.json` 5 个 OJ 预设
- [ ] **周四**
  - [ ] `backend/api/schemas.py` Pydantic 模型对齐 SPEC §6.1
  - [ ] `backend/api/dispatcher.py` 骨架(暂不起 Worker 进程,只返回 mock)
  - [ ] `backend/api/worker_client.py` JSON-RPC 客户端 + 超时处理
- [ ] **周五**
  - [ ] `backend/workers/c_cpp/worker.py` 骨架 + `transformer.py::ConfuseTransformer.handle` 框架(只做"解析 + 报错"两个分支)
  - [ ] `backend/verify/gcc.py` `verify_cpp` 实现 + 单测
  - [ ] **端到端打通**:前端 paste 一段 hello world,后端 parse 报错并把错误位置回显

### 第 2 周(核心混淆策略)

- [ ] **周一**
  - [ ] `c_cpp/transformer.py::_preclean` + `lexer.py` 集成
  - [ ] `c_cpp/transformer.py::_gen_rename_mapping` 实现(S1 改名)
- [ ] **周二**
  - [ ] `c_cpp/transformer.py::_emit_code` 走 PyClang Rewriter / Token 拼接(这是踩坑点,可能一整天都在 debug)
  - [ ] **集成测试**:`backend/tests/test_cpp_rewrite.py`,fixture 是 5~10 个不同风格 C++ 代码(递归、类、模板、lambda、stl)
- [ ] **周三**
  - [ ] `c_cpp/strategy_rename.py` 抽出来,加白名单过滤(`is_user_symbol`)
  - [ ] `c_cpp/strategy_literal.py` S2 数字字面量改写
- [ ] **周四**
  - [ ] `c_cpp/strategy_shuffle_includes.py` S9
  - [ ] `c_cpp/strategy_split_expr.py` S5
  - [ ] `c_cpp/strategy_flatten.py` S3 (单层)
- [ ] **周五**
  - [ ] `c_cpp/strategy_junk.py` S4 (不透明谓词)
  - [ ] 跑 SPEC §12 验收标准前 3 条:50KB / 3s / 编译通过 / 语义等价

### 第 3 周(完成 C/C++ + Python)

- [ ] **周一**
  - [ ] `routes_confuse.py::confuse_with_fallback` 三档降级状态机
  - [ ] `routes_confuse.py` 接到前端,跑通 count=1 端到端
- [ ] **周二**
  - [ ] `backend/workers/python/worker.py` 骨架
  - [ ] `python/transformer.py` 实现 S1 / S2 / S5 / S8 / S9
- [ ] **周三**
  - [ ] `backend/verify/python_ast.py` 验证
  - [ ] Python 端到端跑通
- [ ] **周四**
  - [ ] 前端 `EditorPanel` / `ControlBar` / `ResultPanel` 三个组件搭起来,SPEC §14 的 UI 跑通
  - [ ] `useConfuse.ts` + `useMeta.ts` 两个 hook
- [ ] **周五**
  - [ ] **M1 验收**:跑 SPEC §12 全部 checklist
  - [ ] 修 bug 直到全过
  - [ ] 写 `README.md` 启动说明

> 后续 M2 / M3 / M4 每周计划在 M1 验收通过后再写,不在本文档里预先规划(避免"写而不行")。

---

## 12. 实施期检查清单(可勾选)

实施 M1 时,每完成一块,自检以下问题:

- [ ] 新加的函数都有类型注解(满足 §15.4 "API 路径稳定"的"接口可读")
- [ ] 新加的 API 路由都走 Pydantic 校验
- [ ] 错误响应**只用 `code` 字段判定**,不用 `message` 文案匹配
- [ ] 日志带 `trace_id`(用 `uuid4()`)+ 可选 `user_id`(恒为 None)
- [ ] 响应头 `Cache-Control: no-store`
- [ ] 测试覆盖:每个新策略至少 1 个 fixture 验证"混淆后能编译"+ 1 个 fixture 验证"语义等价"
- [ ] 性能:50KB C++ P95 < 3s(单进程,本地)
- [ ] 隐私:grep 日志确认无 `code` 字段

---

> 文档结束。任何与 SPEC.md 冲突时,以 SPEC.md 为准。
