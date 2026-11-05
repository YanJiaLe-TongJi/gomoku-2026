#define GOMOKU_TEST
#include "../src/brain.cpp"
#include <cassert>
#include <random>
#include <iostream>
using namespace gomoku;
int reference(Board& b, int depth, int alpha, int beta, int side, int last, int ply, int extend) {
    if (last >= 0 && b.makesFive(last, 3-side)) return -MATE+ply;
    if (b.occupied == CELLS) return 0;
    MoveList wins, blocks; b.immediateMoves(side, wins, blocks);
    if (wins.size) return MATE-ply-1;
    if (blocks.size>=2) return -MATE+ply+2;
    bool q=depth<=0;
    if(q && !extend) return b.evaluate(side);
    MoveList moves=blocks.size?blocks:q?b.forcingMoves(side):b.searchCandidates(side,SEARCH_WIDTH);
    int best=q&&!blocks.size?b.evaluate(side):-INF;
    if(best!=-INF){alpha=std::max(alpha,best);if(alpha>=beta)return best;}
    for(int i=0;i<moves.size;++i){int p=moves.moves[i].pos;b.put(p,side);int score=-reference(b,std::max(0,depth-1),-beta,-alpha,3-side,p,ply+1,extend-q);b.undo(p);best=std::max(best,score);alpha=std::max(alpha,score);if(alpha>=beta)break;}
    return best==-INF?b.evaluate(side):best;
}
int main(){
    std::mt19937 rng(34571); int exact=0;
    for(int trial=0;trial<120;++trial){
        Engine e;e.board.resetOpening();int side=1;
        for(int i=0;i<4+trial%32;++i){auto ml=e.board.candidates(side,30);if(!ml.size)break;int p=ml.moves[rng()%ml.size].pos;e.board.put(p,side);if(e.board.makesFive(p,side)){e.board.undo(p);break;}side=3-side;}
        auto before=e.board.cells;auto h=e.board.hash;
        int depth=1+trial%3;int expected=reference(e.board,depth,-INF,INF,side,-1,0,3);
        for(auto& entry:Engine::tt)entry=Engine::Entry{};
        e.deadline=Clock::now()+std::chrono::seconds(20);
        for(auto& row:e.killers)row[0]=row[1]=-1;
        int actual=e.search(depth,-INF,INF,side,-1,0,3);
        if(actual!=expected){std::cerr<<"trial="<<trial<<" expected="<<expected<<" actual="<<actual<<'\n';return 1;}
        assert(!e.stopped && e.board.cells==before && e.board.hash==h);
        auto hits=e.ttHits; assert(e.search(depth,-INF,INF,side,-1,0,3)==expected);assert(e.ttHits>hits || std::abs(expected)>MATE/2);
        // Refill table through a narrow window, then demand an exact full-window result.
        for(auto& entry:Engine::tt)entry=Engine::Entry{};
        e.search(depth,expected-100,expected-99,side,-1,0,3);
        assert(e.search(depth,-INF,INF,side,-1,0,3)==expected);
        ++exact;
    }
    std::cout<<"PASS: "<<exact<<" depth 1-3 positions match independent alpha-beta; TT reuse, bounds and hash restoration\n";
}
