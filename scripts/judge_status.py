"""Read public scoreboard and this user's submission list, without browser credentials."""
import argparse,datetime,json,os,pathlib,sys,urllib.request
from export_games import Document,load_local_config
CONFIG=load_local_config()
BASE=os.environ.get('GOMOKU_JUDGE_URL') or CONFIG.get('judge_url','')
USER=os.environ.get('GOMOKU_USER_ID') or CONFIG.get('user_id','')
def get(path):
    with urllib.request.urlopen(BASE+path,timeout=15) as response:
        return Document(response.read().decode()).root
def main():
    global BASE,USER
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='reports/judge_status_latest.json');ap.add_argument('--queue',action='store_true')
    ap.add_argument('--base-url',default=BASE);ap.add_argument('--user-id',default=USER);a=ap.parse_args()
    if not a.base_url or not a.user_id:ap.error('Provide --base-url and --user-id or configure config/local.json')
    BASE=a.base_url.rstrip('/');USER=a.user_id
    board=get('/');rows=[]
    for tr in board.find('tr'):
        cells=tr.find('td')
        if not cells:continue
        values=[c.text() for c in cells]
        links=[x.attrs.get('href') for x in tr.find('a')]
        if not values[0].startswith('#'):continue
        row=dict(rank=values[0],name=values[1],score=values[2],win=values[3],lose=values[4],draw=values[5],links=links)
        rows.append(row)
    own=next((r for r in rows if '/submission/user/'+USER in r['links']),None)
    doc=get('/submission/user/'+USER);submissions=[]
    for tr in doc.find('tr'):
        links=[a.attrs.get('href','') for a in tr.find('a')]
        links=[u for u in links if u.startswith('/submission/') and u.count('/')==2]
        if links:submissions.append(dict(url=BASE+links[0],text=tr.text()[:300]))
    result=dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),mine=own,top10=rows[:10],leaderboard=rows,submissions=submissions)
    if a.queue:
        queue=get('/submission/running')
        result['queue']=[dict(text=tr.text()[:180],links=[x.attrs.get('href') for x in tr.find('a')])
                         for tr in queue.find('tr') if tr.find('td')]
    output=pathlib.Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def brief(row):
        return dict(row,name=row['name'][:60]) if row else None
    print(json.dumps(dict(checked_at=result['checked_at'],mine=brief(own),top1=brief(rows[0]) if rows else None,tenth=brief(rows[9]) if len(rows)>9 else None,submissions=submissions[:5],queue=result.get('queue')),ensure_ascii=False))
if __name__=='__main__':main()
