# 形式化设计验证的澄清

测试只能覆盖写出来的那几种事件顺序。并发、重试、崩溃恢复这类问题出在**没人想到的交错**上：两个执行者同时拿到"自己是主"的结论，过期的租约持有者迟到写入，重放的消息被处理两次。形式化设计验证要回答的是另一个问题：**这个设计在约定的参数范围内，任何交错下是否都守住了约定的性质。**

它不是一个新场景，而是叠加在修复、开发、优化场景上的一道门槛（研究与文档场景没有可建模的状态机，`init` 会拒绝）。裁判用显式状态模型检查器（TLA+ 的 TLC）穷举模型的状态空间，结论只有两种：**verified**，或一条**具体的反例路径**。

## Table of Contents

- 1. 先筛选：要不要建模
- 2. 三份输入
- 3. 两种模式
- 4. 检查器与命令
- 5. 反例怎么处理
- 6. 不算数的绿色
- 7. 交给实现
- 8. 结论怎么说、证据边界

## 1. 先筛选：要不要建模

只有改动触及下面至少一类行为时才值得建模；否则直接走原场景，不要为了"显得严谨"堆模型：

| 触发项 | 含义 |
|---|---|
| `shared_state` | 多个独立执行者修改共享状态，且先后顺序影响结果 |
| `retry_timeout` | 重试、超时、重复或迟到的消息影响产出 |
| `crash_recovery` | 崩溃恢复影响所有权、去重或持久化顺序 |
| `ownership` | 跨异步变更的授权、租约或资源所有权 |

筛选结论（命中哪几项、为什么）写进检查清单，交付包会原样展示。设计修订引入了新的相关行为时，要重新筛选。

## 2. 三份输入

三份文件都提交在仓库里，检查清单必须冻结（不能位于 `--editable` 之内）：

**design.md：从真实代码与测试复述设计。** 不是愿景文档，而是对现状（或目标设计）的精确复述：需求逐条编号（R1、R2…）、参与者与共享状态、每个动作及其**原子性边界**、显式假设、要注入的故障。每条需求编号与每个故障名都必须在文中出现，裁判会检查。

**模型 `.tla`：只抽象到能回答问题为止。** 模块名与文件名一致；故障（过期、崩溃、消息重复）写成独立动作并组合进 `Next`——定义了却不放进动作组合，等于把真实故障假设掉了，裁判判无效。

**checks.json：判定依据。** 结构如下（配置文件由它确定性生成，不手写 `.cfg`）：

```json
{
  "design": "specs/design.md",
  "screening": {"triggers": ["ownership", "retry_timeout"], "rationale": "租约过期后旧持有者可能迟到写入"},
  "unmodeled": ["时钟漂移与网络分区"],
  "assumptions": ["存储端按 token 比较是原子的"],
  "faults": ["Expire"],
  "cases": [
    {"id": "fence", "kind": "contract", "model": "specs/Lease.tla", "init": "Init", "next": "Next",
     "constants": {"Workers": "{\"a\", \"b\"}", "MaxToken": 3}, "invariants": ["Monotonic"]},
    {"id": "single", "kind": "probe", "model": "specs/Lease.tla", "init": "Init", "next": "Next",
     "constants": {"Workers": "{\"a\", \"b\"}", "MaxToken": 3}, "invariants": ["SingleBeliever"],
     "question": "同一时刻是否只有一个执行者自认为持有租约？"}
  ],
  "coverage": [{"id": "R1", "requirement": "存储里的 token 只增不减", "properties": ["Monotonic"],
                "code": ["src/lease.py"], "tests": ["tests/test_lease.py"]}]
}
```

- `cases[].kind`：`contract` 是约定案例，必须 verified；`probe` 是探针，故意写一条更强的候选约定（"只有一个人自认为是主"），出反例就是**待人裁决的发现**，不阻塞交付。至少要有一个约定案例。
- `init` / `next` 与 `spec` 二选一；`properties` 用于时序性质；`check_deadlock` 默认关闭。
- `unmodeled` 不能为空：没有任何模型能覆盖一切，说不出没建模什么，说明还没想清楚边界。
- `coverage` 双向校验：每条需求声称的性质必须被某个约定案例检查；每个约定案例检查的性质必须映射到某条需求。

## 3. 两种模式

| 模式 | 条件 | 用途 |
|---|---|---|
| 设计迭代 `design` | 模型位于 `--editable` 之内 | 反例驱动修订设计；基线上约定案例有反例时记为未完成，修到 verified 为止 |
| 按已验证设计实现 `implement` | 模型位于 `--editable` 之外（随清单一起冻结） | 设计已定，循环只改代码；基线上约定案例有反例时 `init` 直接拒绝 |

常见的做法是两段：先开一轮设计迭代，把模型修到 verified 并经人批准；再开一轮实现，模型冻结，代码按覆盖矩阵实现，回归测试守住需求。

## 4. 检查器与命令

### 4.1 准备检查器：一个 jar、一个哈希

官方 `tla2tools.jar` 自带标准模块（Naturals、Integers、Sequences、FiniteSets、Bags、TLC、Reals …），但它有三个"换台机器就跑不起来"的缺口：

| 缺口 | 现象 | 处理 |
|---|---|---|
| 社区模块（SequencesExt、FiniteSetsExt、Functions …）不在 jar 里，清单用 `Class-Path` 指向同目录的两个旁路 jar | 缺了旁路文件，`EXTENDS` 社区模块的模型报 `Cannot find source file for module`；只钉 `tla2tools.jar` 的哈希钉不住旁路文件 | 合并成单个自包含的 `tla2tools-full.jar`，清单里不再有 `Class-Path` |
| 字节码目标是 Java 11 | Java 8 上 `UnsupportedClassVersionError`；很多机器根本没装 Java | 找满足版本的 java；没有就下载 Temurin JRE 17 |
| Linux 上 `LC_ALL=C` 等非 UTF-8 区域设置 | 路径含中文等非 ASCII 字符时 Java 打不开文件（`Malformed input`） | 裁判运行检查器时自动补 `LC_ALL=C.UTF-8` |

不要手写这三个参数，用准备脚本：

```bash
python3 <skill>/scripts/evloop_tlc.py fetch --dir ~/.cache/evloop-tlc          # 已装 Java 11+
python3 <skill>/scripts/evloop_tlc.py fetch --dir ~/.cache/evloop-tlc --jre    # 没有 Java 时自动下载 JRE
python3 <skill>/scripts/evloop_tlc.py fetch --dir ~/.cache/evloop-tlc --from /离线目录   # 离线
```

它做四件事：下载钉死版本与 sha256 的 `tla2tools.jar` 和 `CommunityModules-deps.jar`（哈希不符即失败，不回退）；按固定顺序、固定时间戳、不压缩合并成 `tla2tools-full.jar`，**任何机器、任何 Python 版本重建都是同一个字节序列**，合并结果的哈希也写死在脚本里；按 `--java`、`JAVA_HOME`、`PATH`、之前下载的 JRE 的顺序找 Java 11+（`--jre` 按当前系统与架构下载并校验发布方给出的 sha256）；最后在含空格与中文的临时路径里，用裁判自己的命令拼装与解析逻辑跑三个内置模型——标准模块必须 verified、故意违例必须给出反例路径、社区模块必须 verified。全部通过才打印 `init_flags`，可直接粘贴到 `init`。

其余子命令：`bundle --from` 只合并不联网也不需要 Java；`selftest --checker` 对任意 jar 自检（也可用 `--model-cmd` 自检一条现成的约定命令）；`info --checker` 显示 jar 需要的 Java 版本、清单旁路文件是否齐全、能提供哪些模块。检查器目录放在仓库外、跨会话保留的位置，不要提交进仓库。

### 4.2 init 参数与裁判的规则

`init` 的四个参数必须同时给出：

```bash
$J init --scenario bugfix --editable src --frozen tests --test-cmd "python3 -m pytest -q tests" \
  --formal-spec specs/checks.json \
  --checker-path ~/.cache/evloop-tlc/tla2tools-full.jar --checker-sha256 <64 位十六进制> \
  --model-cmd "/path/to/java -XX:+UseParallelGC -cp {checker} tlc2.TLC -tool -noGenerateSpecTE -metadir {metadir} -workers 1 -config {cfg} {model}"
```

- `{checker}` `{model}` `{cfg}` `{metadir}` 四个占位符都必须出现；裁判会自动加引号。
- 必须带 `-tool`（输出可机械解析）与 `-noGenerateSpecTE`（不往工作区写轨迹文件）；不得带 `-continue`（违例后继续会淹没反例）、`-simulate`（随机模拟不是穷举）、`-dfid`（只探索到给定深度）。
- `init` 预检：命令以 java 开头时，检查它的版本不低于 jar 字节码要求；模型 `EXTENDS` / `INSTANCE` 的模块必须由检查器或模型同目录提供（典型失败：只钉了 `tla2tools.jar` 却用了社区模块，会提示改用合并包）。任何一项不满足都直接拒绝。
- 判 verified 需要同时满足：退出码 0、错误级别为 0 的完成消息、统计到大于 0 的不同状态。解析失败、未定义的性质、0 个状态、超时都判**出错**（尝试无效），不会被当成通过；出错时理由里附带诊断（Java 太旧、缺模块、区域设置、找不到 java、内存不足）。
- jar 哈希不符时：`init` 拒绝，`attempt` 判无效，`doctor` 报 `formal_checker` 失败。不做静默回退。`doctor` 另有 `formal_runtime`：复查 Java 版本与模块，并提示与 `init` 时的 Java 是否不同。
- 输入摘要覆盖检查清单、设计文档、模型、生成的配置、jar 哈希与命令。摘要不变的尝试（只改了代码）直接复用基线或之前尝试的结果，不重跑检查器；`verify` 总是重跑。

## 5. 反例怎么处理

每条反例先分类，再动手，分类写进 `review.md`：

| 分类 | 判断 | 修什么 |
|---|---|---|
| 设计缺陷 | 反例路径在真实系统里会发生，且违反了需求 | 改设计（design.md 与模型一起改），在实现模式下则先停下来重新澄清 |
| 建模缺陷 | 路径在真实系统里不可能发生（模型比代码更宽松，或原子性画错了） | 改模型，使其忠于代码；在 design.md 里写清依据 |
| 需求歧义 | 路径是否算违例取决于需求怎么理解 | 停下来问人，把裁决写回需求 |

探针的反例同样要分类，但由人决定它是新需求、已知取舍，还是建模问题。

## 6. 不算数的绿色

下面这些做法能把结果变绿，但都不算数，裁判能拦的会拦，拦不住的必须在评审说明里自查：

- 删掉或弱化性质、把约定案例改成探针——检查清单冻结，改了即无效。
- 把真实故障假设掉：不定义故障动作，或定义了不放进 `Next`——静态检查判无效。
- 缩小范围：把常量调小到撞不上问题、把关键动作合并成一个原子步——清单冻结；模型可改时，评审人要对照 design.md 的原子性边界检查。
- 在实现模式下改模型去迁就代码——模型冻结，改了即无效。

## 7. 交给实现

交付包里的"需求 → 性质 → 代码"表就是实现交接单：每条需求、守护它的性质、对应的代码位置与回归测试。实现者**按已确定的语义实现**；如果某个原子性或顺序在代码里保不住（例如需要跨两次存储调用才能完成），报告阻塞并回到设计迭代，而不是悄悄降级。

## 8. 结论怎么说、证据边界

对外只用一种措辞：**在指定的模型、参数和假设下，检查器完成了检查且未发现被检查性质的违例。** 不说"已证明正确"，也不说"实现没有缺陷"。

交付包会列出证据边界，评审人逐条看：

- `unmodeled` 与 `assumptions` 原样展示；
- 检查是有界的：只覆盖清单里的常量取值；
- 被验证的是抽象，代码与模型的一致性靠覆盖矩阵与回归测试，不靠检查器；
- 检查器 jar 的全部内容由一个 sha256 钉死；Java 运行时不在哈希之内，裁判只检查版本下限并记录 `init` 时的版本（不同 Java 版本对同一模型的结论应一致，但这一点没有被机械保证）；
- 裁判不阻止"跳过建模直接交付"——筛选命中却没建模，要由人在澄清时把关。
