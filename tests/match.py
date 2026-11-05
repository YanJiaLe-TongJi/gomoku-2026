"""用真实 stdin/stdout 管道运行整局；只依赖 Python 标准库。"""
import argparse
import random
import select
import subprocess
import time

N = 12
DIRECTIONS = ((0, 1), (1, 0), (1, 1), (1, -1))


def wins(board, x, y, side):
    for dx, dy in DIRECTIONS:
        count = 1
        for sign in (-1, 1):
            r, c = x + sign * dx, y + sign * dy
            while 0 <= r < N and 0 <= c < N and board[r][c] == side:
                count += 1
                r, c = r + sign * dx, c + sign * dy
        if count >= 5:
            return True
    return False


class Brain:
    def __init__(self, path, side):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, bufsize=0)
        self.times = []
        start = time.monotonic()
        self.send(f"START {side}")
        assert self.read(1.0) == "OK", "START response"
        self.start_seconds = time.monotonic() - start

    def send(self, command):
        self.p.stdin.write((command + "\n").encode())
        self.p.stdin.flush()

    def read(self, timeout):
        deadline = time.monotonic() + timeout
        data = bytearray()
        while not data.endswith(b"\n"):
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.p.stdout], [], [], left)[0]:
                raise AssertionError("response timeout")
            byte = self.p.stdout.read(1)
            if not byte:
                raise AssertionError(f"unexpected EOF, exit={self.p.poll()}")
            data.extend(byte)
        return data.decode().strip()

    def turn(self):
        start = time.monotonic()
        self.send("TURN")
        parts = self.read(2.0).split()
        elapsed = time.monotonic() - start
        self.times.append(elapsed)
        assert elapsed < 2.0
        assert self.start_seconds + sum(self.times) < 90.0
        assert len(parts) == 2, parts
        return tuple(map(int, parts))

    def silent(self):
        assert not select.select([self.p.stdout], [], [], 0.003)[0], "unsolicited output"

    def close(self, result):
        if self.p.poll() is None:
            self.send(f"END {result}")
        self.p.wait(timeout=1.0)
        assert self.p.returncode == 0, self.p.stderr.read().decode()
        assert self.p.stdout.read() == b"", "output after END"
        assert self.p.stderr.read() == b"", "unexpected stderr"
        self.p.stdin.close()
        self.p.stdout.close()
        self.p.stderr.close()


def random_move(board, side, rng):
    empty = [(x, y) for x in range(N) for y in range(N) if not board[x][y]]
    for color in (side, 3 - side):
        winning = [(x, y) for x, y in empty if wins(board, x, y, color)]
        if winning:
            return rng.choice(winning)
    near = [(x, y) for x, y in empty if any(
        board[r][c] for r in range(max(0, x - 2), min(N, x + 3))
        for c in range(max(0, y - 2), min(N, y + 3)))]
    return rng.choice(near or empty)


def play(path, mode, engine_side, seed):
    board = [[0] * N for _ in range(N)]
    for x, y, color in ((5, 6, 1), (6, 5, 1), (5, 5, 2), (6, 6, 2)):
        board[x][y] = color
    brains = {s: Brain(path, s) for s in (1, 2)
              if mode == "self" or s == engine_side}
    rng = random.Random(seed)
    winner = 0
    turns = 0
    try:
        for turn in range(140):
            side = 1 + turn % 2
            if side in brains:
                x, y = brains[side].turn()
            else:
                x, y = random_move(board, side, rng)
            assert 0 <= x < N and 0 <= y < N, (x, y)
            assert board[x][y] == 0, ("occupied", x, y)
            board[x][y] = side
            turns += 1
            if 3 - side in brains:
                brains[3 - side].send(f"PLACE {x} {y}")
                brains[3 - side].silent()
            if wins(board, x, y, side):
                winner = side
                break
        for side, brain in brains.items():
            brain.close(0 if not winner else (1 if side == winner else 2))
        return {"mode": mode, "engine_side": engine_side, "winner": winner,
                "turns": turns,
                "max_turn_s": round(max(t for b in brains.values() for t in b.times), 4),
                "max_total_s": round(max(sum(b.times) for b in brains.values()), 4),
                "max_start_s": round(max(b.start_seconds for b in brains.values()), 4)}
    finally:
        for brain in brains.values():
            if brain.p.poll() is None:
                brain.p.kill()
                brain.p.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("--games", type=int, default=2)
    parser.add_argument("--mode", choices=("self", "random"), default="self")
    args = parser.parse_args()
    for i in range(args.games):
        print(play(args.binary, args.mode, 1 + i % 2, 20261104 + i), flush=True)
