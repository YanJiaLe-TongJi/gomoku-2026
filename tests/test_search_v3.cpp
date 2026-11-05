#define GOMOKU_TEST
#include "../training/search_v3_base.cpp"
#include <cassert>
#include <random>
#include <vector>
using namespace gomoku;

int originalPoint(const Board& b,int p,int side) {
    int score=0,four=0,three=0;
    for(int d=0;d<4;++d) {
        int a[11];
        for(int k=-5;k<=5;++k) {
            int r=p/N+k*DX[d],c=p%N+k*DY[d];
            int v=inside(r,c)?b.cells[index(r,c)]:3;
            a[k+5]=v==0?0:v==side?1:2;
        }
        int before=lineScore(a,11);a[5]=1;
        int gain=lineScore(a,11)-before;score+=gain;four+=gain>=18000;three+=gain>=1200;
    }
    return score+(four>=2?120000:four&&three>=2?18000:three>=2?6000:0);
}
void check(Board& b) {
    for(int p=0;p<CELLS;++p) if(b.empty(p)) for(int s=1;s<=2;++s) {
        assert(b.pointScore(p,s)==originalPoint(b,p,s));
        assert(b.winning[s][p]==b.makesFive(p,s));
        // All immediate threats newly created by p must lie on a line through p.
        auto before=b.cells;
        std::array<bool,CELLS> previous{};
        for(int q=0;q<CELLS;++q) if(q!=p && b.empty(q)) previous[q]=b.makesFive(q,s);
        b.cells[p]=s;bool created=false;
        for(int q=0;q<CELLS;++q) if(b.empty(q) && !previous[q] && b.makesFive(q,s)) created=true;
        b.cells=before;
        // If p itself makes five, overlapping existing fours may make the
        // table's broader four flag redundant. Otherwise it is exact.
        if(!b.winning[s][p] && std::none_of(previous.begin(),previous.end(),[](bool v){return v;}))
            assert(b.forcing[s][p]==created);
    }
}
int main() {
    Board b;std::mt19937 rng(20261105);std::vector<int> moves;
    for(int i=0;i<80;++i) {
        int p;do{p=rng()%CELLS;}while(!b.empty(p));b.put(p,1+i%2);moves.push_back(p);
        if(i%7==0)check(b);
    }
    while(!moves.empty()) {b.undo(moves.back());moves.pop_back();if(moves.size()%9==0)check(b);}
    Engine e;e.board.resetOpening();auto initial=e.board.cells;
    e.deadline=e.vcfDeadline=Clock::now()+std::chrono::seconds(2);e.vcfLimit=0;e.vcfNodes=0;
    assert(e.proveVCF(1,6).state==Engine::UNKNOWN);assert(e.board.cells==initial);
    e.vcfLimit=100;e.vcfNodes=0;e.vcfDeadline=Clock::now()-std::chrono::milliseconds(1);
    assert(e.proveVCF(1,6).state==Engine::UNKNOWN);assert(e.board.cells==initial);
    assert(b.hash == 0);
    Board c; c.resetOpening(); auto h = c.hash;
    for (int p = 0; p < CELLS; ++p) if (c.empty(p)) { c.put(p, 1); c.undo(p); assert(c.hash == h); }
    assert(Engine::fromTT(Engine::toTT(MATE - 9, 4), 7) == MATE - 12);
    assert(Engine::fromTT(Engine::toTT(-MATE + 9, 4), 7) == -MATE + 12);
    std::cout<<"PASS: original point scores, cached wins, forcing points, dirty-cache undo, VCF unknown/restoration\n";
}
