#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Explicit experimental domain extrapolation: original model supports 13..22.
# No board padding or rule change; only allow inference on the adjacent size 12.
python3 - <<'PY'
from pathlib import Path
p=Path('training/rapfi/Rapfi/eval/mixcommon.h')
s=p.read_text()
old='if (!contains(header.supportedBoardSizes, args.boardSize))'
new='if (!contains(header.supportedBoardSizes, args.boardSize) && !(args.boardSize == 12 && contains(header.supportedBoardSizes, 13)))'
if old in s:p.write_text(s.replace(old,new))
elif new not in s:raise RuntimeError('unexpected Rapfi source revision')
PY
cmake -S training/rapfi/Rapfi -B build/teacher -DCMAKE_BUILD_TYPE=Release -DNO_COMMAND_MODULES=ON
cmake --build build/teacher -j 6
cp training/rapfi/Networks/classical/model210901.bin build/teacher/
cp training/rapfi/Networks/mix9svq/mix9svqfreestyle_bsmix.bin.lz4 build/teacher/
teacher_config=${1:-training/teacher.toml}
cp "$teacher_config" build/teacher/config.toml
