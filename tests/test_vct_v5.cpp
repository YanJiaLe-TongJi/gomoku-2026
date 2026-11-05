#define GOMOKU_TEST
#include "../src/brain.cpp"
#include <cassert>
#include <random>
using namespace gomoku;
using Cells = std::array<int,CELLS>;
bool five(const Cells& a,int p,int side){
 for(int d=0;d<4;++d){int n=1;for(int sign:{-1,1})for(int k=1;;++k){int r=p/N+sign*k*DX[d],c=p%N+sign*k*DY[d];if(!inside(r,c)||a[index(r,c)]!=side)break;++n;}if(n>=5)return true;}return false;
}
bool immediate(const Cells& a,int side){for(int p=0;p<CELLS;++p)if(!a[p]&&five(a,p,side))return true;return false;}
// Independent exact all-legal-move mate-in-three test, no cached patterns.
bool mateThree(Cells& a,int side){
 if(immediate(a,side))return true;
 for(int p=0;p<CELLS;++p)if(!a[p]){
  a[p]=side;bool opp=immediate(a,3-side);int wins=0;
  if(!opp)for(int q=0;q<CELLS;++q)if(!a[q]&&five(a,q,side))++wins;
  a[p]=0;if(!opp&&wins>=2)return true;
 }
 return false;
}
bool brute(Cells& a,int attacker,int turn,int depth){
 if(depth<=0)return false;bool has=false;
 for(int p=0;p<CELLS;++p)if(!a[p]){
  has=true;a[p]=turn;bool result=five(a,p,turn)?turn==attacker:brute(a,attacker,3-turn,depth-1);a[p]=0;
  if(turn==attacker&&result)return true;
  if(turn!=attacker&&!result)return false;
 }
 return has&&turn!=attacker;
}
void reset(Engine& e){
 for(auto& x:Engine::threatTT)x=Engine::ThreatEntry{};
 e.deadline=e.vctDeadline=Clock::now()+std::chrono::seconds(30);
 e.vctWork=0;e.vctLimit=1000000;
}
void fork(Engine& e,bool counter){
 e.board.clear();for(int p:{index(6,4),index(6,5),index(4,6),index(5,6)})e.board.put(p,1);
 if(counter){for(int c:{2,3,4})e.board.put(index(1,c),2);}
 else for(int p:{0,2,24,143})e.board.put(p,2);
}
int main(){
 Engine e;fork(e,false);reset(e);auto original=e.board.cells;auto hash=e.board.hash;
 auto p=e.proveVCT(1,3);assert(p.state==Engine::PROVED_WIN);assert(p.plies<=5);assert(e.board.cells==original&&e.board.hash==hash);
 // Check the entire defender quantifier independently for the returned fork.
 Cells a=original;a[p.move]=1;int replies=0;
 for(int q=0;q<CELLS;++q)if(!a[q]){a[q]=2;assert(!five(a,q,2));assert(mateThree(a,1));a[q]=0;++replies;}
 assert(replies>120);
 // A remote open three refutes the tempting central double-three attack.
 fork(e,true);reset(e);e.vctFastAttacks=0;e.board.put(index(6,6),1);auto post=e.board.cells;auto h=e.board.hash;
 auto rejected=e.defendVCT(1,1);assert(rejected.state==Engine::NOT_PROVED);assert(e.board.cells==post&&e.board.hash==h);e.board.undo(index(6,6));
 // Limits must return UNKNOWN, including when a proof has been cached.
 fork(e,false);reset(e);original=e.board.cells;hash=e.board.hash;e.vctLimit=0;
 assert(e.proveVCT(1,3).state==Engine::UNKNOWN);assert(e.board.cells==original&&e.board.hash==hash);
 reset(e);e.vctDeadline=Clock::now()-std::chrono::milliseconds(1);
 assert(e.proveVCT(1,3).state==Engine::UNKNOWN);assert(e.board.cells==original&&e.board.hash==hash);
 // Full, independent minimax on dense 9-empty-cell states. No VCF shortcuts.
 std::mt19937 rng(43921);int proved=0,nonImmediate=0;
 for(int trial=0;trial<160;++trial){
  Cells b{};for(int r=0;r<N;++r)for(int c=0;c<N;++c)b[index(r,c)]=(r+2*c)%4<2?1:2;
  for(int j=0;j<9;++j){int q;do{q=rng()%CELLS;}while(!b[q]);b[q]=0;}
  e.board.clear();for(int q=0;q<CELLS;++q)if(b[q])e.board.put(q,b[q]);reset(e);e.vctFastAttacks=0;int side=1+trial%2;
  auto ref=b;bool exact=brute(ref,side,side,5);auto proof=e.proveVCT(side,2);
  assert(e.board.cells==b);if(proof.state==Engine::PROVED_WIN){assert(exact);assert(proof.plies<=5);++proved;nonImmediate+=!immediate(b,side);}
 }
 std::cout<<"PASS: fork independently checked against "<<replies<<" defenses; remote counter-four rejected; UNKNOWN/restoration; 160 exact minimax positions, "<<proved<<" proofs, "<<nonImmediate<<" non-immediate\n";
}
