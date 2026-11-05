# 离线研究工具

当前可执行引擎已经包含模型和开局谱，运行 `make` 不需要本目录的训练依赖。

公开仓库保留自研搜索基文件、有状态对局接口、策略训练与导出、基础开局谱生成和验证工具。原始比赛数据、教师标签、checkpoint、官方教师及其权重不随仓库分发。需要复现训练时，应自行准备相应数据和教师环境；这里不提供一条命令重建全部历史实验的承诺。

## 搜索与对局

`search_base.cpp`、`search_v3_base.cpp` 到 `search_v6_base.cpp` 是不同阶段的自研搜索实现。`probe_stateful.cpp` 默认包含当前 `src/brain.cpp`；一局一方一个进程，保存 history、TT 和累计时间，使用预算 `-1` 走生产分配路径。

```sh
c++ -std=c++17 -O2 training/probe_stateful.cpp -o build/probe_stateful
python3 training/arena_fixed_openings.py --openings YOUR_OPENINGS.json --baseline OLD_PROBE --challenger NEW_PROBE --ms -1 --output build/arena.json
```

中盘启动并不能恢复之前没有执行过的 TT、history 和用时；本地对局仍不是 Linux 线上成绩。一次只改变一个变量，交换颜色，单 worker，保留全部对局。

## 策略蒸馏

`train_policy.py` 与 `train_scaled_policy.py` 支持学生策略训练，`train_direct_rl.py` 保留初步 PPO 路线，`export_cpp.py` 将学生权重导出为 C++。云端实验使用 MTT S4000 与已有 PyTorch/torch_musa；本机没有安装训练框架。

导出时显式提供模型、基础源码和新的输出文件，避免覆盖冻结版本：

```sh
python3 training/export_cpp.py --model models/c64/tiny_policy.json --base baselines/brain_v1.cpp --output build/new_candidate.cpp
```

训练需要 NumPy/PyTorch，以及可选的 MUSA 后端。当前公开引擎的编译与测试没有这些依赖。教师来源和实验性 12 路适配记录见 `docs/teacher_provenance.json`。

`build_teacher.sh [配置文件]` 需要自行准备 `training/rapfi` 的指定版本源码、Networks 文件和教师 TOML 配置；未给参数时使用本地 `training/teacher.toml`。这些外部输入不随仓库分发。

## 开局谱

`book_generate.py` 使用独立安装的离线教师生成局面，`book_export.py` 编码为 C++ 数据，`book_validate.py` 与 `book_probe.cpp` 验证 D4、行动方和落点；需要自行提供 JSONL 记录与生成的 include 文件。

历史定向修复的完整队列、对手身份和教师缓存只留在本地。当前内嵌 2098 条谱可以直接运行，无需重新生成。
