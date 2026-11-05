#!/usr/bin/env python3
"""Embed trained int8 policy weights and root-only inference into the preserved C++ baseline."""
import argparse,json,pathlib,base64
ROOT=pathlib.Path(__file__).resolve().parents[1]
def floats(v):return ','.join(format(x,'.9g')+('f' if '.' in format(x,'.9g') or 'e' in format(x,'.9g') else '.0f') for x in v)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--model',default=str(ROOT/'models/tiny_policy.json'));ap.add_argument('--output',default=str(ROOT/'build/brain_distilled.cpp'));ap.add_argument('--base',default=str(ROOT/'baselines/brain_v1.cpp'));ap.add_argument('--packed',action='store_true');ap.add_argument('--direct',action='store_true');a=ap.parse_args()
 m=json.load(open(a.model))
 layers=m['layers'];assert len(layers)==5 and layers[0]['shape'][1]==3 and layers[-1]['shape'][0]==1
 for i,l in enumerate(layers):
  oc,ic,kh,kw=l['shape'];assert kh==kw and len(l['weights'])==oc*ic*kh*kw
  assert len(l['scales'])==len(l['bias'])==oc
  if i:assert ic==layers[i-1]['shape'][0]
 width=max(l['shape'][0]for l in layers)
 forward=[f'void tinyPolicy(const Board& board, int side, float* logits) {{\n    float input[3 * CELLS], a[{width} * CELLS], b[{width} * CELLS];',
 '''    for (int p = 0; p < CELLS; ++p) {
        input[p] = float(board.cells[p] == side);
        input[CELLS + p] = float(board.cells[p] == 3 - side);
        input[2 * CELLS + p] = 1.0f;
    }
    using namespace tiny_weights;''']
 previous='input'
 for i,l in enumerate(layers):
  oc,ic,k,_=l['shape'];last=i==len(layers)-1;dest='logits'if last else ('a'if i%2==0 else 'b')
  forward.append(f'    tinyConv({previous}, {ic}, {dest}, {oc}, {k}, {l["dilation"]}, w{i}, s{i}, b{i}, {str(not last).lower()});');previous=dest
 forward.append('}')
 parts=['// Offline distilled policy; weights int8, activations float32.\nnamespace tiny_weights {']
 for i,l in enumerate(m['layers']):
  if a.packed:
   encoded=base64.b85encode(bytes(v&255 for v in l['weights']),pad=True).decode().replace('?',':')
   parts += [f'static signed char w{i}[{len(l["weights"])}];',f'static const char* const packed{i}[] = {{\n'+',\n'.join('"'+encoded[k:k+1000]+'"'for k in range(0,len(encoded),1000))+'\n};']
  else:parts += [f'static constexpr signed char w{i}[] = {{'+','.join(map(str,l['weights']))+'};']
  parts += [f'static constexpr float s{i}[] = {{'+floats(l['scales'])+'};',f'static constexpr float b{i}[] = {{'+floats(l['bias'])+'};']
 if a.packed:
  parts.append('''
void decode(const char* const* chunks, int size, signed char* out, int count) {
    const char* alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>:@^_`{|}~";
    unsigned char map[128] = {};
    for (int i = 0; i < 85; ++i) map[static_cast<unsigned char>(alphabet[i])] = i;
    int pos = 0;
    for (int c = 0; c < size; ++c) for (const char* s = chunks[c]; *s; s += 5) {
        unsigned value = 0;
        for (int j = 0; j < 5; ++j) value = value * 85 + map[static_cast<unsigned char>(s[j])];
        for (int shift = 24; shift >= 0 && pos < count; shift -= 8) {
            int byte = (value >> shift) & 255;
            out[pos++] = static_cast<signed char>(byte < 128 ? byte : byte - 256);
        }
    }
}
void initialize() {
    static bool ready = false;
    if (ready) return;
'''+''.join(f'    decode(packed{i}, sizeof(packed{i}) / sizeof(*packed{i}), w{i}, sizeof(w{i}));\n'for i in range(len(layers)))+'    ready = true;\n}\n')
  forward.insert(1,'    tiny_weights::initialize();')
 parts.append('}\n')
 parts.append('''
// Root only: inference never changes terminal checks, forced blocks or leaf evaluation.
void tinyConv(const float* input, int inChannels, float* output, int outChannels,
              int kernel, int dilation, const signed char* weights,
              const float* scales, const float* bias, bool relu) {
    int padding = kernel / 2 * dilation;
    for (int oc = 0; oc < outChannels; ++oc) {
        float* out = output + oc * CELLS;
        std::fill(out, out + CELLS, bias[oc]);
        for (int ic = 0; ic < inChannels; ++ic)
            for (int ky = 0; ky < kernel; ++ky)
                for (int kx = 0; kx < kernel; ++kx) {
                    int dy = ky * dilation - padding, dx = kx * dilation - padding;
                    float w = float(weights[((oc * inChannels + ic) * kernel + ky) * kernel + kx]) * scales[oc];
                    for (int y = std::max(0, -dy); y < std::min(N, N - dy); ++y)
                        for (int x = std::max(0, -dx); x < std::min(N, N - dx); ++x)
                            out[y * N + x] += input[ic * CELLS + (y + dy) * N + x + dx] * w;
                }
        if (relu) for (int p = 0; p < CELLS; ++p) out[p] = std::max(0.0f, out[p]);
    }
}
__POLICY_FORWARD__
#ifndef GOMOKU_POLICY_EXPAND
#define GOMOKU_POLICY_EXPAND 2
#endif
MoveList policyRoots(const Board& board, int side) {
    MoveList all = board.candidates(side, CELLS), result;
    float logits[CELLS]; tinyPolicy(board, side, logits);
#if GOMOKU_POLICY_EXPAND == 2
    // Protect the original best eight, then fill using equal-weight rank fusion.
    int heuristicRank[CELLS] = {}, modelRank[CELLS] = {};
    MoveList model = all;
    for (int i = 0; i < all.size; ++i) heuristicRank[all.moves[i].pos] = i;
    std::sort(model.moves.begin(), model.moves.begin() + model.size,
              [&](const Move& a, const Move& b) {return logits[a.pos] != logits[b.pos] ? logits[a.pos] > logits[b.pos] : a.pos < b.pos;});
    for (int i = 0; i < model.size; ++i) modelRank[model.moves[i].pos] = i;
    auto combined = [&](const Move& a, const Move& b) {
        int x = heuristicRank[a.pos] + modelRank[a.pos];
        int y = heuristicRank[b.pos] + modelRank[b.pos];
        return x != y ? x < y : heuristicRank[a.pos] < heuristicRank[b.pos];
    };
    bool included[CELLS] = {};
    for (int i = 0; i < std::min(8, all.size); ++i) {
        int p = all.moves[i].pos; result.add(p); included[p] = true;
    }
    std::sort(all.moves.begin(), all.moves.begin() + all.size, combined);
    for (int i = 0; i < all.size && result.size < ROOT_WIDTH; ++i)
        if (!included[all.moves[i].pos]) result.add(all.moves[i].pos);
    std::sort(result.moves.begin(), result.moves.begin() + result.size, combined);
    return result;
#elif GOMOKU_POLICY_EXPAND == 1
    bool included[CELLS] = {};
    for (int i = 0; i < std::min(8, all.size); ++i) {
        int p = all.moves[i].pos; result.add(p); included[p] = true;
    }
    std::sort(all.moves.begin(), all.moves.begin() + all.size,
              [&](const Move& a, const Move& b) {return logits[a.pos] != logits[b.pos] ? logits[a.pos] > logits[b.pos] : a.pos < b.pos;});
    for (int i = 0; i < all.size && result.size < ROOT_WIDTH; ++i)
        if (!included[all.moves[i].pos]) result.add(all.moves[i].pos);
#else
    result = all; result.size = std::min(result.size, ROOT_WIDTH);
#endif
    std::sort(result.moves.begin(), result.moves.begin() + result.size,
              [&](const Move& a, const Move& b) {return logits[a.pos] != logits[b.pos] ? logits[a.pos] > logits[b.pos] : a.pos < b.pos;});
    return result;
}
''')
 source=pathlib.Path(a.base).read_text();source=source.replace('// 五子棋初版：C++17，单文件，无模型、无外部依赖。','// 五子棋策略蒸馏实验版：C++17，单文件，内嵌微型模型，无外部依赖。\n// 教师权重原支持 13~22 路，本训练使用 12 路外推标签；参见训练报告。')
 assert source.count('MoveList roots = board.candidates(mySide, ROOT_WIDTH);')==1
 source=source.replace('class Engine {','\n'.join(parts).replace('__POLICY_FORWARD__','\n'.join(forward))+'\nclass Engine {').replace('MoveList roots = board.candidates(mySide, ROOT_WIDTH);','MoveList roots = policyRoots(board, mySide);')
 if a.direct:
  start=source.index('#ifndef GOMOKU_POLICY_EXPAND');end=source.index('\n} // namespace gomoku',start)
  source=source[:start]+'''
// Direct policy: mandatory immediate win/block checks, otherwise legal argmax.
// No alpha-beta, rollout, external model file or GPU at submission time.
#define GOMOKU_DIRECT_POLICY 1
class Engine {
public:
    Board board;
    int mySide = 1, completedDepth = 0, bestScore = 0;
    unsigned long long nodes = 0;
    double usedSeconds = 0;
    void start(int side) { mySide = side; usedSeconds = 0; board.resetOpening(); }
    int chooseMove(int budget = -1) {
        auto begin = Clock::now();
        MoveList wins, blocks; board.immediateMoves(mySide, wins, blocks);
        if (wins.size) { bestScore = MATE - 1; return wins.moves[0].pos; }
        if (blocks.size) return blocks.moves[0].pos;
        int chosen = -1;
        for (int p = 0; p < CELLS; ++p) if (board.empty(p)) { chosen = p; break; }
        if (chosen < 0 || budget == 0) return chosen;
        float logits[CELLS]; tinyPolicy(board, mySide, logits);
        for (int p = 0; p < CELLS; ++p)
            if (board.empty(p) && logits[p] > logits[chosen]) chosen = p;
        usedSeconds += std::chrono::duration<double>(Clock::now() - begin).count();
        return chosen;
    }
};
'''+source[end:]
  source=source.replace('// 五子棋策略蒸馏实验版：','// 五子棋直接落点策略版（无 Alpha-Beta）：')
  for declaration in ['constexpr int INF = 20000000;','constexpr int MAX_DEPTH = 10;','constexpr int ROOT_WIDTH = 20;','constexpr int SEARCH_WIDTH = 12;','constexpr int THREAT_EXTENSION = 4;']:
   source=source.replace(declaration+'\n','')
 assert len(source.encode())<=1048576, 'Source exceeds 1 MiB; choose a smaller model or packed encoding'
 pathlib.Path(a.output).write_text(source);print(json.dumps({'file':a.output,'source_bytes':len(source.encode()),'weight_bytes':m['weight_bytes'],'parameters':m['parameters']}))
if __name__=='__main__':main()
