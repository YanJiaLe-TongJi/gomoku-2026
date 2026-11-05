// Standalone correctness harness for generated opening-book fragments.
#include <iostream>
#include <chrono>
#ifndef OPENING_BOOK_SOURCE
#define OPENING_BOOK_SOURCE "book_data.inc"
#endif
#include OPENING_BOOK_SOURCE
int main() {
    int side,cells[144];
    while (std::cin>>side) {
        for (int& cell : cells) std::cin>>cell;
        auto start=std::chrono::steady_clock::now();
        int move=opening_book::lookup(cells,side);
        double us=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
        std::cout<<move<<' '<<us<<'\n'<<std::flush;
    }
}
