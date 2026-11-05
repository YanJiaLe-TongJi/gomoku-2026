#define GOMOKU_TEST
#ifndef ENGINE_SOURCE
#define ENGINE_SOURCE "../src/brain.cpp"
#endif
#include ENGINE_SOURCE
#include <cassert>
#include <random>
#include <vector>

using namespace gomoku;

// Instrumented convolutions run much slower; release tests retain 300 ms.
#ifndef GOMOKU_TACTICAL_TEST_MS
#define GOMOKU_TACTICAL_TEST_MS 300
#endif

// 独立重算缓存，检查搜索的落子/撤销是否破坏局面。
void checkBoard(const Board &b) {
    int occupied = 0, total[3] = {};
    std::array<int, CELLS> neighbors{};
    for (int p = 0; p < CELLS; ++p) {
        if (!b.cells[p]) continue;
        ++occupied;
        for (int q = 0; q < CELLS; ++q)
            if (std::abs(p / N - q / N) <= 2 && std::abs(p % N - q % N) <= 2)
                ++neighbors[q];
    }
    for (int i = 0; i < b.lineCount; ++i) {
        const Line &line = b.lines[i];
        for (int side = 1; side <= 2; ++side) {
            int a[N];
            for (int j = 0; j < line.length; ++j) {
                int v = b.cells[line.cells[j]];
                a[j] = v == 0 ? 0 : (v == side ? 1 : 2);
            }
            int score = lineScore(a, line.length);
            assert(score == line.score[side]);
            total[side] += score;
        }
    }
    assert(b.occupied == occupied);
    assert(b.neighbors == neighbors);
    assert(b.total[1] == total[1] && b.total[2] == total[2]);
    assert(b.evaluate(1) == -b.evaluate(2));
}

// 不剪枝的参考 Negamax，在相同候选集合和深度上验证剪枝结果。
int exhaustive(Board &board, int depth, int side, int last, int ply) {
    if (last >= 0 && board.makesFive(last, 3 - side)) return -MATE + ply;
    if (board.occupied == CELLS) return 0;
    MoveList wins, blocks;
    board.immediateMoves(side, wins, blocks);
    if (wins.size) return MATE - ply - 1;
    if (blocks.size >= 2) return -MATE + ply + 2;
    if (!depth) return board.evaluate(side);
    MoveList moves = blocks.size ? blocks :
#ifdef GOMOKU_SEARCH_V2
        board.searchCandidates(side, SEARCH_WIDTH);
#else
        board.candidates(side, SEARCH_WIDTH);
#endif
    int best = -INF;
    for (int i = 0; i < moves.size; ++i) {
        int p = moves.moves[i].pos;
        board.put(p, side);
        int v = -exhaustive(board, depth - 1, 3 - side, p, ply + 1);
        board.undo(p);
        best = std::max(best, v);
    }
    return best == -INF ? board.evaluate(side) : best;
}

void testOpeningAndUndo() {
    Board b;
    assert(b.lineCount == 70);
    b.resetOpening();
    assert(b.occupied == 4);
    assert(b.cells[index(5, 6)] == 1 && b.cells[index(6, 5)] == 1);
    assert(b.cells[index(5, 5)] == 2 && b.cells[index(6, 6)] == 2);
    checkBoard(b);
    auto original = b.cells;
    std::mt19937 rng(20261104);
    std::vector<int> history;
    for (int i = 0; i < 100; ++i) {
        int p;
        do { p = static_cast<int>(rng() % CELLS); } while (!b.empty(p));
        b.put(p, 1 + i % 2);
        history.push_back(p);
        checkBoard(b);
    }
    for (auto it = history.rbegin(); it != history.rend(); ++it) {
        b.undo(*it);
        checkBoard(b);
    }
    assert(b.cells == original);
}

void testFiveAndTactics() {
    for (int side = 1; side <= 2; ++side) {
        for (int d = 0; d < 4; ++d) {
            Board b;
            int x = 0, y = d == 3 ? 11 : 0;
            for (int k = 0; k < 4; ++k) b.put(index(x + k * DX[d], y + k * DY[d]), side);
            int p = index(x + 4 * DX[d], y + 4 * DY[d]);
            assert(b.makesFive(p, side));
            assert(!b.makesFive(p, 3 - side));
            b.put(p, side);
            b.put(index(x + 5 * DX[d], y + 5 * DY[d]), side);
            assert(b.makesFive(p, side)); // 六连也获胜。
        }
        Engine e;
        e.start(side);
        e.board.clear();
        for (int y : {2, 3, 5, 6}) e.board.put(index(0, y), side);
        assert(e.chooseMove(30) == index(0, 4)); // XX.XX。
        e.board.clear();
        for (int y : {2, 3, 5, 6}) e.board.put(index(11, y), 3 - side);
        assert(e.chooseMove(30) == index(11, 4)); // 唯一挡点。
        for (int y : {2, 3, 5, 6}) e.board.put(index(0, y), side);
        assert(e.chooseMove(30) == index(0, 4)); // 自己能赢时不先防守。

        e.board.clear();
        for (int y : {4, 5, 6}) e.board.put(index(6, y), side);
        int p = e.chooseMove(GOMOKU_TACTICAL_TEST_MS);
        assert(p == index(6, 3) || p == index(6, 7)); // 活三变活四。
        assert(e.bestScore > MATE - 10);
        checkBoard(e.board);
    }
}

void testSearch() {
    Engine e;
    e.start(1);
    std::mt19937 rng(71);
    int side = 1, last = -1;
    for (int sample = 0; sample < 6; ++sample) {
        e.deadline = Clock::now() + std::chrono::seconds(30);
        e.stopped = false;
        auto original = e.board.cells;
        int actual = e.search(2, -INF, INF, side, last, 0, 0);
        assert(!e.stopped);
        int expected = exhaustive(e.board, 2, side, last, 0);
        assert(actual == expected);
        assert(e.board.cells == original);
        checkBoard(e.board);
        MoveList candidates = e.board.candidates(side, 8);
        last = candidates.moves[rng() % candidates.size].pos;
        e.board.put(last, side);
        side = 3 - side;
    }

    e.start(1);
    auto initial = e.board.cells;
    for (int budget : {0, 1, 15, 60}) {
        int p = e.chooseMove(budget);
        assert(e.board.empty(p));
        assert(e.board.cells == initial);
        checkBoard(e.board);
    }
    // 没有终局五连的近满盘，覆盖候选点很少及和棋叶子。
    e.board.clear();
    for (int x = 0; x < N; ++x)
        for (int y = 0; y < N; ++y)
            e.board.put(index(x, y), 1 + ((x + 2 * y) % 4 >= 2));
    for (int p = 0; p < CELLS; ++p) assert(!e.board.makesFive(p, e.board.cells[p]));
    e.board.undo(index(11, 11));
    assert(e.chooseMove(20) == index(11, 11));
    e.board.put(index(11, 11), 1 + ((11 + 2 * 11) % 4 >= 2));
    assert(e.chooseMove(20) == -1);
    checkBoard(e.board);
}

int main() {
    testOpeningAndUndo();
    testFiveAndTactics();
    testSearch();
    std::cout << "PASS: opening, cached evaluation, undo, four directions, long lines, "
                 "win/block priority, forced win, alpha-beta reference, timeout, full board\n";
}
