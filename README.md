# 鼠鬚管 Squirrel

鼠鬚管（Squirrel）是 [Rime 中州韻輸入法引擎](https://rime.im) 的 macOS 前端，基于 InputMethodKit 构建，适用于 macOS 13.0 及以上版本。

本仓库是上游 [rime/squirrel](https://github.com/rime/squirrel) 的分叉，在保留上游全部功能的基础上，增加一项实验性能力：**LLM 候选词重排序**——候选呈现给用户之前，由本地运行的轻量语言模型结合当前会话上文，在同一重排组内重新调整候选的发射顺序，同时保留系统词典权重、用户词典权重与既有候选生成逻辑。

[![Download](https://img.shields.io/github/v/release/Habit130/squirrel)](https://github.com/Habit130/squirrel/releases/latest)
[![Build Status](https://github.com/Habit130/squirrel/actions/workflows/commit-ci.yml/badge.svg)](https://github.com/Habit130/squirrel/actions/workflows)

> 当前为实验性开发分支：尚未发布正式安装包，LLM 重排序需要从源码构建并自行部署本地模型服务（见「安装」）。

## 特性

- 上游 Squirrel / Rime 的全部功能：拼音输入、方案切换、用户词典、同步、主题定制等
- LLM 候选词重排序：
  - 完全本地推理（Qwen3-0.6B-Base，MLX），输入内容不出本机
  - 独立推理进程（daemon），Unix socket **同步有界交换**（默认 200 ms），超时或故障则整窗原序透传（[ADR-0001](docs/adr/0001-inference-process-boundary.md)，[公共合同](docs/reranker-public-contract.md)）
  - 窗口化、无状态、按请求打分：上文条件是 daemon 的 `--context-window`（默认 64 字符），与方案里的 `window`（候选条数，默认 32）不是同一项（[ADR-0002](docs/adr/0002-windowed-stateless-scoring.md)）
  - 任何打分故障都整窗原序透传，不改变候选集合、不阻塞文本提交
  - 与 librime-octagram、librime-lua 等既有插件共存
- 当前范围：仅简体中文输入方案（以 `luna_pinyin` 为开发基准）

## 安装

> 目前没有开箱即用的安装包，以下两步均面向开发者与早期试用者。

1. **构建应用**：从源码构建 Squirrel，步骤见 [INSTALL.md](INSTALL.md)。
2. **部署重排序服务**：构建并安装 `llm_rerank` 插件（随本仓库的 librime 子模块构建），部署 daemon 与模型权重。插件安装方式见 [librime-llm-rerank](https://github.com/Habit130/librime-llm-rerank)。

初次安装后，若在部分应用中打不出字，请注销并重新登录。

## 使用

- 在系统输入法列表中选择「鼠鬚管」，通过 `Ctrl+`` `（或 `F4`）呼出方案菜单、切换输入方式
- LLM 重排序通过输入方案的 `llm_rerank` 过滤器配置。下列键值与已发布插件 `v1.0.2` 的默认值一致；省略 `socket_path` 时才会用 `$HOME/.../llm-rerank.sock`，显式值按字面使用（`~` 不会展开）。完整协议与阻塞语义见 [公共合同](docs/reranker-public-contract.md)。

```yaml
engine:
  filters:
    - llm_rerank
llm_rerank:
  reranking_enabled: true
  recording_enabled: false
  evidence_enabled: false
  window: 32
  alpha: 0.0
  sys_coeff: 1.0
  usr_coeff: 1.0
  gamma: 2.0
  saturate_k: 3.0
  deadline_ms: 200
  baseline_policy_id: mean-token-lm-v1
```

`alpha` 默认 `0.0`，语言模型项关闭；要联系 daemon 必须设为正值。其他可调项（`verbose`、`socket_path`）见公共合同。

## 工作原理

- 候选列表由 librime 生成并完成基础排序，本仓库的 Swift 前端只负责渲染与翻页，不重排候选（[CONTEXT.md](CONTEXT.md)）
- 重排发生在 librime 插件层（[librime-llm-rerank](https://github.com/Habit130/librime-llm-rerank)）：在候选产出后、呈现前，以本次会话上文为条件重新调整同一重排组内候选的发射顺序
- 设计规格见 [issue #16](https://github.com/Habit130/squirrel/issues/16)；架构决策见 [docs/adr/](docs/adr/)；已发布配置与协议见 [公共合同](docs/reranker-public-contract.md)

## Roadmap

- **第一阶段（进行中）**：通用 LLM 候选重排——已完成插件与打包（[#26](https://github.com/Habit130/squirrel/pull/26)），后续完善体验验收与配置收敛
- **第二阶段（规划中）**：语义个性化候选重排——以本地语义记忆复用用户的历史选择：保存可重放的选择事件，在语义相近而非字面相同的上文下复用既往偏好，同时严格区分零检索证据与真故障，任何故障都沿用整次原序透传。规格见 [issue #43](https://github.com/Habit130/squirrel/issues/43)

## 关联仓库

| 仓库 | 说明 |
| --- | --- |
| [Habit130/librime-llm-rerank](https://github.com/Habit130/librime-llm-rerank) | 候选重排插件源码（librime 插件，BSD-3-Clause） |

## 构建与贡献

- 构建环境、依赖与发布流程：[INSTALL.md](INSTALL.md)
- 仓库工作约定（分支、提交规范、评审流程）：[AGENTS.md](AGENTS.md)
- 问题与需求：本仓库 [Issues](https://github.com/Habit130/squirrel/issues)；插件代码请提交到 [librime-llm-rerank](https://github.com/Habit130/librime-llm-rerank)

## 授权与致谢

本仓库基于上游 [rime/squirrel](https://github.com/rime/squirrel)（式恕堂 版權所無）分叉，沿用其 [GPL v3](LICENSE.txt) 授权。上游的完整版权与致谢（输入方案设计、程序设计与美术贡献者、所引用的开源软件清单）见上游仓库的 [README](https://github.com/rime/squirrel/blob/master/README.md)。

感谢 [Rime 社区](https://github.com/rime/home) 与上游 Squirrel 的所有贡献者。
