# 有状态对局接口

`probe_stateful.cpp` 默认包含 `src/brain.cpp`，一个进程对应一局中的一个固定执棋方。每回合只重建 Board，保留 Engine 的 history、累计 usedSeconds、TT 和正证明缓存。需要比较其他版本时用 `GOMOKU_STATEFUL_SOURCE` 编译宏覆盖路径。

输入为 `s side budget_ms cell0 ... cell143`。`side` 为 1 或 2，不能在同一进程内切换。新对局创建新进程。输出 JSON 包括落点、完成深度、节点数、用时、TT 命中，以及前后 history 指纹和累计时间。

预算 `-1` 走生产自动分配路径；非负预算显式覆盖单手时间，但仍累计实际消耗。固定 1100ms 并不自动构成整局90秒保证。中盘启动不能恢复此前没有执行过的 history、TT 和用时。

`make test` 会运行 `tests/test_stateful_probe.py`，比较10次正式协议与probe选点，并检查普通搜索后的历史和累计用时继续保留。它是接口一致性检查，不是平台强杀超时测试或棋力评测。
