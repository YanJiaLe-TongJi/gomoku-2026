#!/usr/bin/env python3
"""Replace only the book bytes in frozen submission7 for a controlled v5 A/B."""
import argparse,hashlib,json,pathlib

def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',default='baselines/brain_submission7_candidate.cpp')
    ap.add_argument('--old-book',default='training/book_data_full.inc')
    ap.add_argument('--new-book',default='training/book_data_corrections.inc')
    ap.add_argument('--output',default='training/book_candidate_v5.cpp')
    ap.add_argument('--report',default='reports/opening_book_candidate_manifest.json');a=ap.parse_args()
    source=pathlib.Path(a.source).read_bytes();old=pathlib.Path(a.old_book).read_bytes();new=pathlib.Path(a.new_book).read_bytes()
    assert source.count(old)==1,'Frozen source must contain exactly the supplied original book bytes'
    candidate=source.replace(old,new,1)
    assert len(candidate)<=1048576
    assert source.replace(old,b'BOOK_PLACEHOLDER',1)==candidate.replace(new,b'BOOK_PLACEHOLDER',1)
    pathlib.Path(a.output).write_bytes(candidate)
    report=dict(source=a.source,source_sha256=sha(source),output=a.output,bytes=len(candidate),sha256=sha(candidate),
                original_book_bytes=len(old),candidate_book_bytes=len(new),
                identical_search_model_protocol_bytes=True,only_change='opening book fragment')
    pathlib.Path(a.report).write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
