// One process represents one game and one fixed engine side.
// Build another candidate with -DGOMOKU_STATEFUL_SOURCE='"../candidate.cpp"'.
// Input: s side budget_ms followed by 144 cells. -1 uses production budgeting.
// Board snapshots replace only Board; Engine history, timers and static TTs persist.
#define GOMOKU_TEST
#ifndef GOMOKU_STATEFUL_SOURCE
#define GOMOKU_STATEFUL_SOURCE "../src/brain.cpp"
#endif
#include GOMOKU_STATEFUL_SOURCE

using namespace gomoku;

namespace {
std::uint64_t historyFingerprint(const Engine& engine) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (const auto& row : engine.history)
        for (int value : row) { hash ^= static_cast<unsigned>(value); hash *= 1099511628211ULL; }
    return hash;
}
int historyNonzero(const Engine& engine) {
    int count = 0;
    for (const auto& row : engine.history) for (int value : row) count += value != 0;
    return count;
}
}

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    std::cout.precision(17);

    Engine engine;
    bool started = false;
    int turn = 0;
    char mode;
    int side, budgetMs;
    while (std::cin >> mode >> side >> budgetMs) {
        if (mode != 's' || (side != 1 && side != 2) || budgetMs < -1) {
            std::cerr << "Expected s, side 1/2, and budget_ms >= -1\n";
            return 2;
        }
        std::array<int, CELLS> cells{};
        for (int& cell : cells) {
            if (!(std::cin >> cell) || cell < 0 || cell > 2) {
                std::cerr << "Expected 144 cells in range 0..2\n";
                return 2;
            }
        }
        if (!started) {
            engine.start(side);
            started = true;
        } else if (side != engine.mySide) {
            std::cerr << "A stateful probe process belongs to one game and one fixed side\n";
            return 2;
        }

        const double usedBefore = engine.usedSeconds;
        const std::uint64_t historyBefore = historyFingerprint(engine);
        // clear() restores every Board encoding/cache. It does not reset Engine.
        engine.board.clear();
        for (int p = 0; p < CELLS; ++p) if (cells[p]) engine.board.put(p, cells[p]);
        const std::uint64_t originalHash = engine.board.hash;
        const auto begin = Clock::now();
        const int move = engine.chooseMove(budgetMs);
        if (engine.board.cells != cells || engine.board.hash != originalHash) {
            std::cerr << "Search did not restore the input board\n";
            return 4;
        }
        if (move >= 0) {
            if (!engine.board.empty(move)) {
                std::cerr << "Search returned an illegal move\n";
                return 4;
            }
            // Production TURN also places the returned own move before responding.
            engine.board.put(move, side);
        }
        const double elapsedMs = std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
        ++turn;
        std::cout << "{\"pos\":" << move
                  << ",\"depth\":" << engine.completedDepth
                  << ",\"nodes\":" << engine.nodes
                  << ",\"score\":" << engine.bestScore
                  << ",\"tt_hits\":" << engine.ttHits
                  << ",\"tt_cuts\":" << engine.ttCuts
                  << ",\"ms\":" << elapsedMs
                  << ",\"turn\":" << turn
                  << ",\"used_seconds_before\":" << usedBefore
                  << ",\"used_seconds\":" << engine.usedSeconds
                  << ",\"history_before\":\"" << historyBefore << '\"'
                  << ",\"history_after\":\"" << historyFingerprint(engine) << '\"'
                  << ",\"history_nonzero\":" << historyNonzero(engine)
                  << ",\"generation\":" << static_cast<unsigned>(Engine::generation)
                  << "}\n" << std::flush;
    }
    return 0;
}
