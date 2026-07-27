# 候选排序无头评测脚手架

对应 [issue #8](https://github.com/Habit130/squirrel/issues/8)。让候选排序改动可以用一条命令跑出可比的数字，而不是靠手敲几个词凭感觉判断。

## 跑法

```sh
scripts/eval/run.sh
```

首次运行会在 `scripts/eval/.venv/`（gitignored）建一个本地 venv 并装 `pypinyin`，之后复用。除此之外不写任何仓库内文件。

前置条件：`librime/build/bin/rime_api_console` 必须已经编出来（连同它旁边的 `default.yaml` / `luna_pinyin.schema.yaml` / `luna_pinyin.dict.yaml` / `essay.txt` 等 minimal 数据）。这是 librime 从源码构建的产物之一，见根目录 `CLAUDE.md` 的 "From-source build" 一节；`tools/CMakeLists.txt` 里这个 target 不受任何 CMake option 门控，正常 `make librime` 就会带出来。没有的话 `run_eval.py` 会直接报错并指回这里，不会静默跳过。

## 硬约束：绝不碰 `~/Library/Rime`

每次运行 `run_eval.py` 会：

1. 把 `librime/build/bin/` 里那份 minimal `rime_dir`（schema / dict / essay 等文件，不含二进制）复制一份到 `mktemp -d` 生成的临时目录。
2. 以该临时目录为 `cwd` 启动 `rime_api_console`——这个工具的 `shared_data_dir`/`user_data_dir` 永远是 `.`（它从不读命令行参数设置这两个路径，见 `rime_api_console.cc` 的 `main()`），所以 cwd 就决定了整套数据（含它自己部署出的 `build/`、`*.userdb`）落在哪。
3. 跑完之后删除这个临时目录（`--keep-tmp` 可以保留，用于调试）。

全程不 `cd` 进 `librime/build/bin/` 本身跑，也不会碰真正在用的 `~/Library/Rime`。每次运行都是一份全新、空白的用户词典状态，两次运行之间可比。

## 语料怎么来的

`corpus/sentences.txt`：纯简体中文句子，一行一句，不含标点/数字/字母/空格。想扩量直接加句子，不需要手写拼音——这正是 issue 里要求的"句子 → 拼音 → 期望还原原句"，而不是手写 `(pinyin, hanzi)` pair。

拼音由 [pypinyin](https://github.com/mozillazg/python-pinyin) 在**整句**上做上下文相关的多音字消歧（`lazy_pinyin(sentence, style=Style.NORMAL)`），例如"银行"正确给出 `yin hang` 而不是逐字瞎猜。曾经尝试过完全不依赖 pypinyin、只用 `luna_pinyin.dict.yaml` 自带的单字权重挑"最可能"读音，但这份 minimal 词典里相当一部分多音字的几个读音**都没有权重字段**（比如"开"的四行 `bing`/`jian`/`kai`/`yan` 全部没有百分比），挑最大权重在平局时退化成"文件里第一行赢"，"开"因此被解成 `bing`——这是常见字，不是生僻字才踩到，所以放弃了这条路，改用 pypinyin。

即便如此，生成的每个字的读音仍会反查 `luna_pinyin.dict.yaml`：如果 pypinyin 给出的读音根本不在这个字的词典条目里（原则上不可能回退成功），整句跳过并在 stderr 报原因。当前语料 120 句、0 句被跳过。

单行拼音超过 99 字符（`LineEditor` 的输入缓冲区上限，`librime/tools/line_editor.h`）也会被跳过——这不会发生在日常长度的句子上，只是防御性检查。

## 评测协议

单个 `rime_api_console` 进程跑完整个语料（不是每句重启一次，省掉重复部署的开销）。对每句：

```
{Escape}                       清空上一句留下的组字状态
<句子的连续拼音>                 一次性整句输入,不做增量选字
print candidate list            控制台自带命令,拿到未分页的完整候选序列
set option __eval_marker__      哨兵行,标记这句的输出到此结束
```

`print candidate list` 用的是 `Menu::GetCandidateAt` 迭代器，也就是 `menu.cc` 里"filter 链最后一环发射顺序"那条真实链路——不是简单复述自动打印的、被 `page_size=5` 截断的那一页。

**候选类别怎么判的**：`rime_api_console` 通过 C API 拿到的 `RimeCandidate` 只有 `text`/`comment`，没有暴露 `Candidate::type()`；要拿到真类别得给 `rime_api_console.cc` 加字段，这已经是碰 librime 源码，超出本 ticket "只搭脚手架" 的范围。退而求其次用启发式：rank-1 候选的（去简繁转换包装后的）文本如果直接命中 `luna_pinyin.dict.yaml` 的某个词条 key，判为"词类"；否则判为"非词类"（这份语料的输入字母表只有连续小写拼音字母，不会触发标点候选，schema 也没接 `predictor` 组件，所以"非词类"在这里实际上就是"整句"）。这是近似值，不是精确类型标签，但对"这个 rank-1 是不是永远抢不掉"这个是/否问题足够用。

## 指标

- **top-1 / top-5**：还原出的整句候选（`text` 与原句逐字相等）出现在候选序列前 1 / 前 5 名的比例。
- **MRR**：`1/rank` 的平均值，找不到记 0。
- **rank-1 非词类候选比例**：见下方"为什么加这个指标"。

### 一个结构性观察：本语料下 top-1 恒等于 top-5 恒等于 MRR

当前跑出来 top-1 = top-5 = MRR，不是巧合也不是 bug——每句测的是**整句还原**（span 恰好是 `[0, 句子长度)`），根据合并序判据（起点相同时终点越大越先），能落进这个 span 的候选只有"整句"类。而 Poet 的 BeamSearch 对同一个 span 似乎只发射**一个**整句候选（没有观察到宽度为 7 的 beam 里其余分支也各自变成独立候选），所以目标句子要么是这个 span 唯一成员、排第一，要么整个候选序列里都找不到——没有中间地带。换句话说，rank 只会取 1 或"未找到"两个值中的一个。这条结论只对"单次整句输入、不做增量选字"这种评测方式成立；后续如果换成逐段选字的评测方法，三个指标会重新分开。

### 为什么加"rank-1 非词类候选比例"

重排的分组键是 `(起点, 终点, 类别)`，组间顺序按各组首次出现位置固定死——组内重排（不管换什么打分方式）永远没法把一个词候选提到一个更早出现的整句候选前面。如果某句的 rank-1 已经被一个（错误的）整句候选占住，未来任何只作用于候选内部排序的方案都救不了这一句。这个比例就是"重排能改善 top-1 的天花板"，直接喂给 #6（"grammar" 槽位放什么）和 #22（系数标定）。

## 当前基线数字

```
$ scripts/eval/run.sh
cases evaluated:        120
cases skipped:          0
not found in dump:      50
top-1:                  70/120 = 0.583
top-5:                  70/120 = 0.583
MRR:                    0.583
rank-1 non-word rate:   120/120 = 1.000
```

跑出时间：约 2.5 秒（含一次性部署）。环境：macOS 27.0 (26A5388g) / arm64，librime submodule `33e78140250125871856cdc5b42ddc6a5fcd3cd4`。

**这不是"纯词频"基线**：octagram 插件二进制已加载，但语法数据缺失，`Grammar::Query` 恒返回 `-12`，逐词累加后等效于一个偏好"更少更长的词"的长度先验——细节见 #2 的 Notes 和 #9。上面 `not found` 的 50 句里能看到这个先验的实际效果：例如"这家餐厅的菜很好吃"被还原成"这家餐厅德才很好吃"——"的菜"两个高频单字词被"德才"这一个（罕见但确实在词典里）双字词顶替，只因为它把词数从 2 降到 1，省下一份 `-12` 的惩罚，不是因为"德才"真的更常见。另外 `他/她` 同音混淆在 `not found` 里出现得非常多，这正是本项目要解决的核心问题（见根目录 `CONTEXT.md` 与 #2）。#9 把语法数据装上之后应该重跑这份脚手架，产出新的对照基线。

## 扩量

往 `corpus/sentences.txt` 加句子即可，一行一句，纯汉字。`run_eval.py` 会自动生成拼音、校验字符/读音覆盖，扩到几百上千句不需要改代码。
