# 历史引擎归档

`engines/` 保存原先散落在根目录的自研引擎文件，迁移没有改变其内容。原文件名、新位置和 SHA256 见 `engine_manifest.json`。当前提交入口始终是 `../src/brain.cpp`。

- `brain.cpp` 是早期无模型版，不是当前版本。
- `brain_book_expanded.cpp`、`brain_book_expanded_v2.cpp`、`brain_book_expanded_v3.cpp` 分别对应实际第 9、10、11 版。
- `brain_search_book_v6.cpp` 是未提交的搜索候选。
- `brain_search_book_v7.cpp` 的名字容易误导：实际为旧 v4 搜索加 2278 条谱，不是当前 v6 的后继。
- `../baselines/brain_submission9.cpp` 是未提交的旧准备文件；实际第 9 版应看 `brain_submission9_book1262.cpp`。

原始本地报告中的根目录 `brain*.cpp` 路径现在对应 `archive/engines/` 下同名文件。旧远程中转版本含部署信息，仅保留于被忽略的本地归档，不公开。
