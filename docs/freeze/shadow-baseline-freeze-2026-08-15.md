# 影子基线冻结记录(Shadow Baseline Freeze Record)

- **契约**:AC-75-v1(Squirrel #75,冻结基线并启动 γ=0 影子记录)
- **冻结日期**:2026-08-15(UTC)
- **状态**:影子记录进行中;本记录不可修改,变更走新冻结记录(AC75-6)

## 1. 冻结基线策略身份(baseline_policy_id)

```text
frozen-baseline-v1:rule=mean-token-lm-v1:model=Qwen3-0.6B-Base:tokenizer=Qwen3-0.6B-Base:norm=exact-text:fail=fail-closed-passthrough:squirrel=9c47df777958:plugin=ce58c72017db:alpha=0.0:beta_sys=1.0:beta_usr=1.0
```

构成逐项(AC75-1,全部为冻结时部署事实):

| 组件 | 值 | 来源 |
| --- | --- | --- |
| 规则版本 | `frozen-baseline-v1` | 合成格式版本 |
| token 平均规则 | `mean-token-lm-v1` | daemon `mean_token` 策略绑定 id |
| 模型身份 | `Qwen3-0.6B-Base` | daemon `MODEL_PATH` 目录名 |
| 分词器身份 | `Qwen3-0.6B-Base` | 模型目录内 Qwen3 分词器 |
| 候选规范化 | `exact-text` | 插件按候选文本精确比较(无额外 NFC 转换) |
| 失败语义 | `fail-closed-passthrough` | #45:任一打分故障整窗原序透传 |
| squirrel 代码 SHA | `9c47df777958` | 部署构建树 HEAD(origin/master) |
| 插件代码 SHA | `ce58c72017db` | 部署的插件提交(feat/baseline-policy-id HEAD);dylib 构建自 e401405,其 C++ 与 ce58c72 逐字节相同 |
| α | `0.0` | #46 owner 决定默认 α=0(LM 项关闭) |
| β_sys / β_usr | `1.0` / `1.0` | 默认系数 |

任何组件变化(代码 SHA、模型、token 规则、α/β、规范化、失败语义)→ 推导出新
policy ID → 需要新冻结记录与新的开发目标 HLC 起点(AC75-6)。

## 2. 双仓库 SHA

- squirrel:`9c47df777958b9424c7048bb5ba5f6cadc9c5da5`(origin/master HEAD,部署构建树)
- librime-llm-rerank:部署的插件提交 `ce58c72017db640b823adb87beb014da155e2bc9`(feat/baseline-policy-id HEAD)。
  dylib 构建自 `e4014051e7dd1236851e4fe8a06fdfafe3d5cc6a`,其 C++ 与 ce58c72 逐字节相同
  (e401405→ce58c72 差量仅 daemon/status_core.py 与 daemon/test_status.py)
- librime 子模块:`33e78140250125871856cdc5b42ddc6a5fcd3cd4`(1.17.0)

## 3. 配置快照(部署真相源)

用户侧 `~/Library/Rime/luna_pinyin.custom.yaml`(repo 内 shipped 默认值未变,#94):

```yaml
patch:
  switches/@2/reset: 1
  engine/processors:
    - llm_rerank_recorder
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
  "engine/filters/+":
    - llm_rerank
  llm_rerank/recording_enabled: true
  llm_rerank/reranking_enabled: true
  llm_rerank/evidence_enabled: false
  llm_rerank/baseline_policy_id: "frozen-baseline-v1:..." # 见第 1 节全文
```

运行语义:可见重排开、记录开、证据关(γ=0);α=0 默认(LM 项关闭,可见排序
= 冻结基础策略的 weight-only base ordering)。

## 4. HLC 水位(开发目标边界)

- **冻结水位(首个开发目标 HLC 起点)**:`hlc_physical_ms=1786806466751, hlc_logical=0`
  - clear 重建后的新历史(`history_id dc3ffbf1a21957e0bb4ceed535c9df56`,
    `store_epoch 8407bd6b456ba5c5a526b4b95951bac3`)中首个事件 HLC。
  - 事件 `hlc <= 1786805828927/0`(clear 前旧历史)全部视为冻结前事件:只作历史
    正证据,不作开发或前瞻确认目标标签(AC75-3)。旧历史已备份保留(见第 6 节)。
- **事实库身份**:`history_id dc3ffbf1a21957e0bb4ceed535c9df56`,
  `store_epoch 8407bd6b456ba5c5a526b4b95951bac3`,fact schema v1,event format v1。
- **水位证明**:`squirrel-semantic-memory status` 的 `facts.fact_high_water` 即
  当前记录水位;冻结水位以上事件为开发目标事件。

## 5. RISK-75-1(继承自 RISK-53-1,AC-53-v3)

- **触发**:进程 marker 创建失败 + 独占维护租约仅内存持有 commit + 证据前崩溃的复合窗口。
- **影响**:影子期个别选择事件静默缺失,诊断不确定;不影响已提交文本、既有事实、候选回退。
- **遏制**:插件 README 残留声明;损失机制与候选身份无关,不偏置方案对比。
- **复审**:#80 锁定配置时,或出现窗口内损失证据时。

## 6. 证据与验证(摘要,完整矩阵见 issue #75 handback)

- 冻结前事件备份:`~/Documents/squirrel-memory-backup-20260815.squirrel-memory-backup`
  (1569 events,sha256 `b2f44689...`,`backup verify` 通过)
- clear 验证:旧 epoch `9c72c368...` → 新 epoch `8407bd6b...`,`clear --yes
  --expect-store-epoch` 成功,清空后 status 0 事件、exit 0
- 活机抽查:新历史记录 8 个 dev-target 事件,首个 HLC `1786806466751/0`,
  确认来源含 explicit_current 与 explicit_indexed
- 机制验证:冻结 ID 被 daemon 接受;错误 rule / 错误 model 均 `policy_mismatch`
- 测试:daemon 362/362、C++ 281/281(含 γ=0 等价 `GammaZeroKeepsBaseScoreOrder`
  与 `ZeroEvidenceStillUsesCompleteBaseStrategy`、`GammaZeroKeepsFrozenBasePolicyActive`)
