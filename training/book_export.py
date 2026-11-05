#!/usr/bin/env python3
"""Export exact-board-checked D4 opening book as a standalone C++17 fragment."""
import argparse, base64, collections, hashlib, json, pathlib
from book_generate import board_of, canonical, pack, won

MASK=(1<<64)-1
def board_hash(signature,side):
    value=14695981039346656037
    for byte in signature+bytes([side]):value=((value^byte)*1099511628211)&MASK
    return value

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',default='data/opening_book/positions.jsonl')
    ap.add_argument('--output',default='training/book_data.inc')
    ap.add_argument('--report',default='reports/opening_book_export.json');a=ap.parse_args()
    records={};seen_hashes=collections.Counter()
    for e in map(json.loads,pathlib.Path(a.input).read_text().splitlines()):
        b=board_of(e['history']);key,h=canonical(e['history'])
        assert key==e['key'] and b==board_of(h)
        assert e['side']==1+len(e['history'])%2
        assert 0<=e['move']<144 and b[e['move']]==0
        assert not any(won(b,p,s)for p,s in enumerate(b)if s)
        immediate={1:[],2:[]}
        for p in range(144):
            if b[p]:continue
            for side in (1,2):
                b[p]=side
                if won(b,p,side):immediate[side].append(p)
                b[p]=0
        if immediate[e['side']]:assert e['move'] in immediate[e['side']], 'Book misses immediate win'
        elif len(immediate[3-e['side']])==1:assert e['move']==immediate[3-e['side']][0], 'Book misses unique forced block'
        signature=pack(b);value=board_hash(signature,e['side']);seen_hashes[value]+=1
        record=value.to_bytes(8,'little')+signature+bytes([e['side'],e['move']])
        assert key not in records,'Duplicate key'
        records[key]=(value,record)
    data=b''.join(row[1]for row in sorted(records.values()))
    encoded=base64.b85encode(data,pad=True).decode().replace('?',':')
    strings='\n'.join('    "'+encoded[i:i+1000]+'",'for i in range(0,len(encoded),1000))
    n=len(records);maxstones=max(len(e['history'])for e in map(json.loads,pathlib.Path(a.input).read_text().splitlines()))
    code=f'''// Offline Rapfi opening book: {n} positions, complete board and side validation.
// 12x12 freestyle; original teacher model supports 13..22, adapted experimentally.
// Call opening_book::lookup(board.cells, side) before normal search; -1 means miss.
// D4 transforms preserve absolute stone colors. No network, files or dynamic allocation.
#ifndef GOMOKU_OPENING_BOOK_DATA
#define GOMOKU_OPENING_BOOK_DATA
namespace opening_book {{
constexpr int kCount = {n};
constexpr int kStride = 46;
constexpr int kBytes = kCount * kStride;
constexpr int kMaxStones = {maxstones};
static const char* const kEncoded[] = {{
{strings}
}};
static unsigned char kTable[kBytes];
inline bool initialize() {{
    const char* alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>:@^_`{{|}}~";
    unsigned char digits[256] = {{}};
    for (int i=0; i<85; ++i) digits[static_cast<unsigned char>(alphabet[i])] = static_cast<unsigned char>(i);
    unsigned long long acc=0; int used=0, output=0;
    for (const char* text : kEncoded) for (const char* p=text; *p; ++p) {{
        acc=acc*85+digits[static_cast<unsigned char>(*p)];
        if (++used==5) {{
            for (int shift=24; shift>=0; shift-=8)
                if (output<kBytes) kTable[output++]=static_cast<unsigned char>((acc>>shift)&255);
            acc=0; used=0;
        }}
    }}
    return output==kBytes && used==0;
}}
inline int transform(int p, int t) {{
    int r=p/12, c=p%12;
    if (t>=4) c=11-c;
    for (int i=0; i<(t&3); ++i) {{ int previous=r; r=c; c=11-previous; }}
    return r*12+c;
}}
inline unsigned long long keyAt(int i) {{
    unsigned long long key=0;
    for (int b=0; b<8; ++b) key|=static_cast<unsigned long long>(kTable[i*kStride+b])<<(b*8);
    return key;
}}
template<class Cells> int lookup(const Cells& cells, int side) {{
    if (side!=1 && side!=2) return -1;
    int count[3]={{}};
    for (int p=0; p<144; ++p) {{
        int cell=cells[p]; if (cell<0 || cell>2) return -1; ++count[cell];
    }}
    int stones=count[1]+count[2];
    if (stones<4 || stones>kMaxStones || count[1]!=count[2]+(side==2)) return -1;
    unsigned char canonical[36]={{}}; int chosen=0;
    for (int t=0; t<8; ++t) {{
        unsigned char candidate[36]={{}};
        for (int p=0; p<144; ++p) {{
            int q=transform(p,t);
            candidate[q/4]|=static_cast<unsigned char>(cells[p]<<((q%4)*2));
        }}
        bool less=t==0;
        if (t!=0) for (int i=0; i<36; ++i) {{
            if (candidate[i]!=canonical[i]) {{ less=candidate[i]<canonical[i]; break; }}
        }}
        if (less) {{ for (int i=0; i<36; ++i) canonical[i]=candidate[i]; chosen=t; }}
    }}
    unsigned long long hash=14695981039346656037ULL;
    for (unsigned char byte : canonical) hash=(hash^byte)*1099511628211ULL;
    hash=(hash^static_cast<unsigned>(side))*1099511628211ULL;
    static const bool ready=initialize(); if (!ready) return -1;
    int lo=0,hi=kCount;
    while (lo<hi) {{ int mid=lo+(hi-lo)/2; if (keyAt(mid)<hash) lo=mid+1; else hi=mid; }}
    for (int i=lo; i<kCount && keyAt(i)==hash; ++i) {{
        const unsigned char* record=kTable+i*kStride;
        bool same=record[44]==side;
        for (int j=0; j<36 && same; ++j) same=record[j+8]==canonical[j];
        if (same) for (int p=0; p<144; ++p)
            if (transform(p,chosen)==record[45]) return cells[p]==0?p:-1;
    }}
    return -1;
}}
}} // namespace opening_book
#endif
'''
    pathlib.Path(a.output).write_text(code)
    report=dict(positions=n,record_bytes=len(data),source_bytes=len(code.encode()),
                source_sha256=hashlib.sha256(code.encode()).hexdigest(),max_stones=maxstones,
                duplicate_hash_groups=sum(v>1 for v in seen_hashes.values()),
                exact_board_check=True,side_absolute=True,transformations=8)
    pathlib.Path(a.report).write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
