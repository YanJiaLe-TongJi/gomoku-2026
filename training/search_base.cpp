// 五子棋搜索改进版：C++17，连续冲四证明、威胁延伸、局部模式缓存。
// 规则：12x12，自由五子棋，连续五子及以上获胜。
// 提交本文件即可。标准输出只包含协议要求的 OK 和落点。
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <string>

namespace gomoku {

#define GOMOKU_SEARCH_V2 1

constexpr int N = 12;
constexpr int CELLS = N * N;
constexpr int MATE = 10000000;
constexpr int INF = 20000000;
constexpr int MAX_DEPTH = 10;
constexpr int ROOT_WIDTH = 20;
constexpr int SEARCH_WIDTH = 12;
constexpr int THREAT_EXTENSION = 8;
constexpr int DX[4] = {0, 1, 1, 1};
constexpr int DY[4] = {1, 0, 1, -1};
using Clock = std::chrono::steady_clock;

#ifndef GOMOKU_MOVE_BUDGET_MS
#define GOMOKU_MOVE_BUDGET_MS 1100
#endif

bool inside(int x, int y) { return x >= 0 && x < N && y >= 0 && y < N; }
int index(int x, int y) { return x * N + y; }

struct Move {
    int pos = -1;
    int priority = 0;
};

struct MoveList {
    std::array<Move, CELLS> moves{};
    int size = 0;
    void add(int p, int priority = 0) { moves[size++] = {p, priority}; }
};

struct Line {
    std::array<int, N> cells{};
    int length = 0;
    int score[3] = {};
};

// a[] 使用 0=空、1=己方、2=对方/边界。
// 五格窗口累计发展潜力；四子威胁按不同成五空位去重。
// 这些分值是初版启发式参数，不是精确胜率。
int lineScore(const int *a, int length) {
    int score = 0;
    unsigned winningPoints = 0;
    for (int start = 0; start + 5 <= length; ++start) {
        int stones = 0, blocked = 0, empty = -1;
        for (int j = start; j < start + 5; ++j) {
            stones += a[j] == 1;
            blocked += a[j] == 2;
            if (a[j] == 0) empty = j;
        }
        if (blocked) continue;
        if (stones == 5) score += 500000;
        else if (stones == 4) winningPoints |= 1u << empty;
        else if (stones == 3) score += 120;
        else if (stones == 2) score += 12;
        else if (stones == 1) score += 1;
    }
    int wins = 0;
    for (unsigned mask = winningPoints; mask; mask &= mask - 1) ++wins;
    if (wins >= 2) score += 150000;
    else if (wins == 1) score += 18000;

    // .XXX..、.XX.X. 等两端开放的三子结构。
    for (int start = 0; start + 6 <= length; ++start) {
        if (a[start] != 0 || a[start + 5] != 0) continue;
        int stones = 0, blocked = 0;
        for (int j = start + 1; j < start + 5; ++j) {
            stones += a[j] == 1;
            blocked += a[j] == 2;
        }
        if (!blocked && stones == 3) score += 1200;
    }
    return score;
}

// Ten neighbours of an empty point, ternary encoded relative to one side.
// The table implements exactly the original pointScore directional gain.
struct Pattern { int gain = 0; bool five = false, four = false; };
const std::array<Pattern, 59049>& patternTable() {
    static const auto table = [] {
        std::array<Pattern, 59049> result{};
        for (int key = 0; key < 59049; ++key) {
            int a[11] = {}, n = key;
            for (int j = 0; j < 11; ++j) if (j != 5) { a[j] = n % 3; n /= 3; }
            int before = lineScore(a, 11); a[5] = 1;
            result[key].gain = lineScore(a, 11) - before;
            for (int start = 1; start <= 5; ++start) {
                int own = 0, opp = 0;
                for (int j = start; j < start + 5; ++j) { own += a[j] == 1; opp += a[j] == 2; }
                result[key].five |= own == 5;
                result[key].four |= own == 4 && opp == 0;
            }
        }
        return result;
    }();
    return table;
}

class Board {
public:
    std::array<int, CELLS> cells{};
    std::array<int, CELLS> neighbors{};
    std::array<std::array<int, 4>, CELLS> lineIds{};
    std::array<Line, 70> lines{};
    int lineCount = 0;
    int occupied = 0;
    int total[3] = {};
    mutable std::array<bool, CELLS> dirty{};
    mutable int pointValue[3][CELLS] = {};
    mutable bool winning[3][CELLS] = {}, forcing[3][CELLS] = {};

    Board() {
        dirty.fill(true);
        (void)patternTable();
        // 每格恰好属于横、竖和两个斜向的四条线。
        for (int d = 0; d < 4; ++d) {
            for (int x = 0; x < N; ++x) {
                for (int y = 0; y < N; ++y) {
                    if (inside(x - DX[d], y - DY[d])) continue;
                    Line &line = lines[lineCount];
                    for (int r = x, c = y; inside(r, c); r += DX[d], c += DY[d]) {
                        int p = index(r, c);
                        line.cells[line.length++] = p;
                        lineIds[p][d] = lineCount;
                    }
                    ++lineCount;
                }
            }
        }
    }

    void clear() {
        dirty.fill(true);
        cells.fill(0);
        neighbors.fill(0);
        occupied = 0;
        total[1] = total[2] = 0;
        for (int i = 0; i < lineCount; ++i)
            lines[i].score[1] = lines[i].score[2] = 0;
    }

    void resetOpening() {
        clear();
        // 作业 PDF 第 7 页的固定初始局面，坐标是 (行, 列)。
        put(index(5, 6), 1);
        put(index(6, 5), 1);
        put(index(5, 5), 2);
        put(index(6, 6), 2);
    }

    bool empty(int p) const { return p >= 0 && p < CELLS && cells[p] == 0; }

    void refreshLines(int p) {
        for (int d = 0; d < 4; ++d) {
            Line &line = lines[lineIds[p][d]];
            for (int side = 1; side <= 2; ++side) {
                int a[N];
                for (int j = 0; j < line.length; ++j) {
                    int c = cells[line.cells[j]];
                    a[j] = c == 0 ? 0 : (c == side ? 1 : 2);
                }
                total[side] -= line.score[side];
                line.score[side] = lineScore(a, line.length);
                total[side] += line.score[side];
            }
        }
    }

    void updateNeighbors(int p, int delta) {
        int x = p / N, y = p % N;
        for (int r = std::max(0, x - 2); r <= std::min(N - 1, x + 2); ++r)
            for (int c = std::max(0, y - 2); c <= std::min(N - 1, y + 2); ++c)
                neighbors[index(r, c)] += delta;
    }

    void put(int p, int side) {
        cells[p] = side;
        ++occupied;
        updateNeighbors(p, 1);
        refreshLines(p);
        invalidate(p);
    }

    void undo(int p) {
        cells[p] = 0;
        --occupied;
        updateNeighbors(p, -1);
        refreshLines(p);
        invalidate(p);
    }

    void invalidate(int p) {
        dirty[p] = true;
        for (int d = 0; d < 4; ++d) for (int k = -5; k <= 5; ++k) {
            int r = p / N + k * DX[d], c = p % N + k * DY[d];
            if (inside(r, c)) dirty[index(r, c)] = true;
        }
    }

    void refreshPoint(int p) const {
        if (!dirty[p]) return;
        const auto& table = patternTable();
        int score[3] = {}, fours[3] = {}, threes[3] = {};
        winning[1][p] = winning[2][p] = forcing[1][p] = forcing[2][p] = false;
        for (int d = 0; d < 4; ++d) {
            int key1 = 0, key2 = 0, factor = 1;
            for (int k = -5; k <= 5; ++k) if (k) {
                int r = p / N + k * DX[d], c = p % N + k * DY[d];
                int v = inside(r, c) ? cells[index(r, c)] : 3;
                key1 += factor * (v == 0 ? 0 : v == 1 ? 1 : 2);
                key2 += factor * (v == 0 ? 0 : v == 2 ? 1 : 2);
                factor *= 3;
            }
            const Pattern* patterns[3] = {nullptr, &table[key1], &table[key2]};
            for (int s = 1; s <= 2; ++s) {
                const Pattern& pat = *patterns[s];
                score[s] += pat.gain; fours[s] += pat.gain >= 18000; threes[s] += pat.gain >= 1200;
                winning[s][p] |= pat.five; forcing[s][p] |= pat.four;
            }
        }
        for (int s = 1; s <= 2; ++s) {
            if (fours[s] >= 2) score[s] += 120000;
            else if (fours[s] && threes[s] >= 2) score[s] += 18000;
            else if (threes[s] >= 2) score[s] += 6000;
            pointValue[s][p] = score[s];
        }
        dirty[p] = false;
    }

    // 可用于已经落下的棋子，也可假设在空位 p 落下 side 棋子。
    bool makesFive(int p, int side) const {
        int x = p / N, y = p % N;
        for (int d = 0; d < 4; ++d) {
            int count = 1;
            for (int sign : {-1, 1}) {
                int r = x + sign * DX[d], c = y + sign * DY[d];
                while (inside(r, c) && cells[index(r, c)] == side) {
                    ++count;
                    r += sign * DX[d];
                    c += sign * DY[d];
                }
            }
            if (count >= 5) return true;
        }
        return false;
    }

    int evaluate(int side) const {
        int value = total[side] - total[3 - side];
        return std::clamp(value, -500000, 500000);
    }

    // 全棋盘检查，直接胜负点不受距离筛选或候选数量限制。
    void immediateMoves(int side, MoveList &wins, MoveList &blocks) const {
        for (int p = 0; p < CELLS; ++p) {
            if (cells[p]) continue;
            refreshPoint(p);
            if (winning[side][p]) wins.add(p);
            if (winning[3 - side][p]) blocks.add(p);
        }
    }

    int pointScore(int p, int side) const {
        refreshPoint(p);
        return pointValue[side][p];
    }

    MoveList forcingMoves(int side) const {
        MoveList moves;
        for (int p = 0; p < CELLS; ++p) if (!cells[p]) {
            refreshPoint(p);
            if (forcing[side][p]) moves.add(p, pointValue[side][p]);
        }
        std::sort(moves.moves.begin(), moves.moves.begin() + moves.size,
                  [](const Move& a, const Move& b) { return a.priority != b.priority ? a.priority > b.priority : a.pos < b.pos; });
        return moves;
    }

    MoveList searchCandidates(int side, int limit) const {
        MoveList moves = candidates(side, limit), threats = forcingMoves(side);
        bool included[CELLS] = {};
        for (int i = 0; i < moves.size; ++i) included[moves.moves[i].pos] = true;
        for (int i = 0; i < threats.size; ++i) if (!included[threats.moves[i].pos]) moves.add(threats.moves[i].pos);
        return moves;
    }

    MoveList candidates(int side, int limit) const {
        MoveList list;
        for (int p = 0; p < CELLS; ++p) {
            if (cells[p] || (occupied && neighbors[p] == 0)) continue;
            int center = 22 - std::abs(2 * (p / N) - 11) - std::abs(2 * (p % N) - 11);
            int attack = pointScore(p, side);
            int defense = pointScore(p, 3 - side);
            list.add(p, attack + defense + defense / 10 + center);
        }
        std::sort(list.moves.begin(), list.moves.begin() + list.size,
                  [](const Move &a, const Move &b) {
                      if (a.priority != b.priority) return a.priority > b.priority;
                      return a.pos < b.pos;
                  });
        list.size = std::min(list.size, limit);
        return list;
    }
};

class Engine {
public:
    Board board;
    int mySide = 1;
    double usedSeconds = 0;
    int completedDepth = 0;
    int bestScore = 0;
    unsigned long long nodes = 0;
    bool stopped = false;
    Clock::time_point deadline;
    Clock::time_point vcfDeadline;
    int vcfNodes = 0, vcfLimit = 0;
    enum ProofState { NOT_PROVED, PROVED_WIN, UNKNOWN };
    struct Proof { ProofState state = NOT_PROVED; int move = -1, plies = 0; };

    // Attacker chooses only moves making a four; a single block is forced.
    // UNKNOWN means node/time exhaustion, never a proof of safety or defeat.
    Proof proveVCF(int attacker, int attacks) {
        if (++vcfNodes > vcfLimit || Clock::now() >= vcfDeadline || Clock::now() >= deadline)
            return {UNKNOWN, -1, 0};
        MoveList wins, dangers;
        board.immediateMoves(attacker, wins, dangers);
        if (wins.size) return {PROVED_WIN, wins.moves[0].pos, 1};
        if (dangers.size >= 2 || attacks <= 0 || board.occupied == CELLS) return {};
        MoveList moves = dangers.size ? dangers : board.forcingMoves(attacker);
        for (int i = 0; i < moves.size; ++i) {
            int p = moves.moves[i].pos;
            board.put(p, attacker);
            MoveList threats, counterWins;
            board.immediateMoves(attacker, threats, counterWins);
            Proof child;
            if (threats.size && !counterWins.size) {
                if (threats.size >= 2) child = {PROVED_WIN, p, 1};
                else {
                    int q = threats.moves[0].pos;
                    board.put(q, 3 - attacker);
                    child = proveVCF(attacker, attacks - 1);
                    board.undo(q);
                }
            }
            board.undo(p);
            if (child.state == PROVED_WIN) return {PROVED_WIN, p, child.plies + 2};
            if (child.state == UNKNOWN) return child;
        }
        return {};
    }

    void start(int side) {
        mySide = side;
        usedSeconds = 0;
        board.resetOpening();
    }

    bool outOfTime() {
        if (!stopped && Clock::now() >= deadline) stopped = true;
        return stopped;
    }

    // 返回值始终从当前 side 的角度解释。
    // last 是上一手；extend 控制深度耗尽后强制防守的延伸上限。
    int search(int depth, int alpha, int beta, int side, int last,
               int ply, int extend) {
        ++nodes;
        if (outOfTime()) return 0; // stopped 单独传播，此 0 不参与最终决策。
        if (last >= 0 && board.makesFive(last, 3 - side)) return -MATE + ply;
        if (board.occupied == CELLS) return 0;

        MoveList wins, blocks;
        board.immediateMoves(side, wins, blocks);
        if (wins.size) return MATE - ply - 1;
        if (blocks.size >= 2) return -MATE + ply + 2;

        bool quietSearch = depth <= 0;
        if (quietSearch && extend == 0) return board.evaluate(side);
        MoveList moves = blocks.size ? blocks : quietSearch ? board.forcingMoves(side) : board.searchCandidates(side, SEARCH_WIDTH);
        // A non-forcing move is represented by static stand-pat, never by a
        // fabricated mate/loss when all explored forcing attempts fail.
        int best = quietSearch && !blocks.size ? board.evaluate(side) : -INF;
        if (best != -INF) { alpha = std::max(alpha, best); if (alpha >= beta) return best; }
        for (int i = 0; i < moves.size; ++i) {
            if (outOfTime()) return 0;
            int p = moves.moves[i].pos;
            board.put(p, side);
            int score = -search(std::max(0, depth - 1), -beta, -alpha, 3 - side,
                                p, ply + 1, extend - (depth <= 0));
            // 不论正常、剪枝还是超时，都先撤销这一手。
            board.undo(p);
            if (stopped) return 0;
            best = std::max(best, score);
            alpha = std::max(alpha, score);
            if (alpha >= beta) break;
        }
        return best == -INF ? board.evaluate(side) : best;
    }

    // overrideBudgetMs 仅供本地测试；平台主程序使用默认预算。
    int chooseMove(int overrideBudgetMs = -1) {
        auto begin = Clock::now();
        completedDepth = 0;
        bestScore = 0;
        nodes = 0;
        stopped = false;
        int remainingMoves = std::max(1, (CELLS - board.occupied + 1) / 2);
        double remainingMs = std::max(0.0, 85000.0 - usedSeconds * 1000.0);
        int budget = std::min(GOMOKU_MOVE_BUDGET_MS,
                              static_cast<int>(remainingMs / remainingMoves));
        budget = std::max(1, budget);
        if (overrideBudgetMs >= 0) budget = overrideBudgetMs;
        deadline = begin + std::chrono::milliseconds(budget);

        auto finish = [&](int p) {
            usedSeconds += std::chrono::duration<double>(Clock::now() - begin).count();
            return p;
        };

        MoveList wins, blocks;
        board.immediateMoves(mySide, wins, blocks);
        if (wins.size) {
            bestScore = MATE - 1;
            return finish(wins.moves[0].pos);
        }
        if (blocks.size) {
            // 没有自己的立即胜利时，唯一挡点就是唯一能继续的走法。
            // 多挡点意味着不可同时防住，仍输出合法位置。
            bestScore = blocks.size >= 2 ? -MATE + 2 : 0;
            return finish(blocks.moves[0].pos);
        }

        // 先备好合法落点，即使第一轮搜索被打断也能正常输出。
        int chosen = -1;
        for (int p = 0; p < CELLS; ++p)
            if (board.empty(p)) { chosen = p; break; }
        if (chosen < 0 || outOfTime()) return finish(chosen);
        MoveList roots = board.candidates(mySide, ROOT_WIDTH);
        if (roots.size) chosen = roots.moves[0].pos;

        int provedLoss[CELLS] = {};
        if (budget >= 10 && !outOfTime()) {
            auto phaseEnd = std::min(deadline, Clock::now() + std::chrono::milliseconds(std::min(180, budget / 4)));
            vcfDeadline = std::min(phaseEnd, Clock::now() + std::chrono::milliseconds(std::min(50, budget / 12)));
            vcfNodes = 0; vcfLimit = 6000;
            Proof own = proveVCF(mySide, 6);
            if (own.state == PROVED_WIN) { bestScore = MATE - own.plies; return finish(own.move); }
            vcfDeadline = phaseEnd;
            for (int i = 0; i < roots.size && Clock::now() < phaseEnd; ++i) {
                int p = roots.moves[i].pos; board.put(p, mySide);
                vcfNodes = 0; vcfLimit = 1500;
                Proof opp = proveVCF(3 - mySide, 6);
                board.undo(p);
                if (opp.state == PROVED_WIN) provedLoss[p] = -MATE + 1 + opp.plies;
            }
            // Even if iterative deepening is interrupted, avoid a proven loss
            // when an unproved alternative is available. Unproved != safe.
            std::stable_sort(roots.moves.begin(), roots.moves.begin() + roots.size,
                [&](const Move& a, const Move& b) { return provedLoss[a.pos] > provedLoss[b.pos]; });
            if (roots.size) chosen = roots.moves[0].pos;
        }

        for (int depth = 1; depth <= MAX_DEPTH && !outOfTime(); ++depth) {
            // 上轮最佳着优先，有助于更早收紧 alpha/beta 窗口。
            for (int i = 0; i < roots.size; ++i)
                if (roots.moves[i].pos == chosen) {
                    std::swap(roots.moves[0], roots.moves[i]);
                    break;
                }
            int iterationBest = -INF, iterationMove = chosen, alpha = -INF;
            for (int i = 0; i < roots.size; ++i) {
                if (outOfTime()) break;
                int p = roots.moves[i].pos;
                int score = provedLoss[p];
                if (!score) {
                    board.put(p, mySide);
                    score = -search(depth - 1, -INF, -alpha, 3 - mySide,
                                    p, 1, THREAT_EXTENSION);
                    board.undo(p);
                }
                if (stopped) break;
                if (score > iterationBest) {
                    iterationBest = score;
                    iterationMove = p;
                }
                alpha = std::max(alpha, score);
            }
            if (stopped) break; // 只保留完整完成的一轮。
            chosen = iterationMove;
            bestScore = iterationBest;
            completedDepth = depth;
            if (std::abs(bestScore) >= MATE - CELLS - THREAT_EXTENSION) break;
            double elapsedMs = std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
            if (elapsedMs >= budget * 0.65) break;
        }
        return finish(chosen);
    }
};

} // namespace gomoku

#ifndef GOMOKU_TEST
int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    gomoku::Engine engine;
    bool started = false;
    std::string command;
    while (std::cin >> command) {
        if (command == "START") {
            int side;
            if (!(std::cin >> side) || (side != 1 && side != 2)) return 0;
            engine.start(side);
            started = true;
            std::cout << "OK\n" << std::flush;
        } else if (command == "PLACE") {
            int x, y;
            if (!(std::cin >> x >> y)) return 0;
            if (!started || !gomoku::inside(x, y)) continue;
            int p = gomoku::index(x, y);
            if (engine.board.empty(p)) engine.board.put(p, 3 - engine.mySide);
        } else if (command == "TURN") {
            if (!started) continue;
            int p = engine.chooseMove();
            if (!engine.board.empty(p)) return 0; // 满盘时协议应发送 END。
            engine.board.put(p, engine.mySide);
            std::cout << p / gomoku::N << ' ' << p % gomoku::N << '\n' << std::flush;
        } else if (command == "END") {
            int result;
            std::cin >> result;
            break;
        } else {
            std::string rest;
            std::getline(std::cin, rest);
        }
    }
    return 0;
}
#endif
