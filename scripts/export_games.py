#!/usr/bin/env python3
"""只读导出 Next-Makyek 提交的比赛、棋谱与 JSONL 日志，无第三方依赖。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_local_config():
    path = ROOT / "config/local.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


DEFAULT_URL = os.environ.get("GOMOKU_SUBMISSION_URL") or load_local_config().get("submission_url")
SCHEMA = 1
FINISHED = {"win", "lose", "draw"}


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c
                                 for c in self.children).split())

    def find(self, tag=None, cls=None, **attrs):
        out = []
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if ((tag is None or child.tag == tag)
                    and (cls is None or cls in child.attrs.get("class", "").split())
                    and all(child.attrs.get(k) == v for k, v in attrs.items())):
                out.append(child)
            out.extend(child.find(tag, cls, **attrs))
        return out


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.stack[-1].children.append(n)
        if tag not in self.VOID:
            self.stack.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def one(nodes, what):
    if not nodes:
        raise ValueError(f"页面缺少 {what}；可能需要登录或页面格式变化")
    return nodes[0]


def result_class(node):
    statuses = set(node.attrs.get("class", "").split())
    return next((s for s in ("win", "lose", "draw", "pending", "running", "error")
                 if s in statuses), "unknown")


def parse_submission(source, url, submission_id):
    root = Document(source).root
    table = one(root.find("tbody", id="match_row_container"), "比赛表")
    matches = []
    for row in table.find("tr"):
        status = one(row.find("a", "match-status--text"), "比赛状态")
        challenger = one(row.find("td", "col--challenger"), "Challenger")
        opponent = one(row.find("td", "col--challengee"), "Opponent")
        if any(n.text() == "(Submitter)" for n in challenger.find("span", "text-aqua")):
            mine, other = "0", opponent
        elif any(n.text() == "(Submitter)" for n in opponent.find("span", "text-aqua")):
            mine, other = "1", challenger
        else:
            raise ValueError("比赛行无法识别本次提交的身份")
        other_link = one(other.find("a"), "对手提交链接")
        timestamp = [n for n in row.find("span") if n.attrs.get("data-timestamp")]
        matches.append({
            "match_id": row.attrs["data-id"], "url": urljoin(url, status.attrs["href"]),
            "submission_id": submission_id, "my_brain_id": mine,
            "result": result_class(status), "opponent": other_link.text(),
            "opponent_submission_url": urljoin(url, other_link.attrs["href"]),
            "at": int(timestamp[0].attrs["data-timestamp"]) if timestamp else None,
        })
    pages = [urljoin(url, a.attrs["href"]) for a in root.find("a", "pager__item")
             if re.fullmatch(r"/submission/" + re.escape(submission_id) + r"(?:/\d+)?",
                             urlsplit(urljoin(url, a.attrs["href"])).path)]
    pages = [p[:-2] if urlsplit(p).path.endswith("/1") else p for p in pages]
    return matches, pages


def parse_match(source, match):
    root = Document(source).root
    table = one(root.find("tbody", id="round_row_container"), "局列表")
    out = []
    for row in table.find("tr"):
        links = [n for n in row.find("a") if "/round/" in n.attrs.get("href", "")]
        if not links:
            continue
        url = urljoin(match["url"], links[0].attrs["href"])
        column = "col--challenger" if match["my_brain_id"] == "0" else "col--challengee"
        mine = one(row.find("td", column), "己方结果")
        status = one(mine.find("span", "round-status--text"), "单局状态")
        number = one(row.find("td", "col--round-no"), "局号").text().lstrip("#")
        out.append({"round_id": urlsplit(url).path.rsplit("/", 1)[-1],
                    "round_number": int(number), "url": url,
                    "result": result_class(status)})
    return out


def parse_round_page(source, url):
    root = Document(source).root
    one(root.find("script", id="roundSummary"), "棋局摘要")
    # 不执行网页脚本，只解析指定 JSON 数据块。
    block = re.search(r'<script\b[^>]*\bid=["\']roundSummary["\'][^>]*>(.*?)</script>',
                      source, re.S)
    if not block:
        raise ValueError("缺少 roundSummary JSON")
    summary = json.loads(unescape(block.group(1)))
    log_link = one([a for a in root.find("a")
                    if urlsplit(a.attrs.get("href", "")).path.endswith("/logs")], "日志链接")
    return summary, urljoin(url, log_link.attrs["href"])


def parse_logs(raw, my_brain_id):
    records = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    initial = board = summary = config = None
    moves, attempts, errors = [], [], []
    pending, responses = {}, {}
    next_field = 1
    for event in records:
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        action = data.get("action")
        if action == "initialize":
            config = data
        elif action == "clearBoard":
            initial = [row[:] for row in data["board"]]
            board = [row[:] for row in initial]
            next_field = data.get("nextField", 1)
        elif action == "sendRequest" and data.get("data") == "TURN":
            pending[str(data["id"])] = event["at"]
        elif action == "receiveResponse":
            brain = str(data["id"])
            if brain in pending and re.fullmatch(r"\s*\d+\s+\d+\s*", str(data.get("data"))):
                responses[brain] = {"response": data["data"].strip(),
                                    "response_ms": event["at"] - pending.pop(brain)}
        elif action == "place":
            attempts.append({"field": data.get("field"), "position": data.get("position"),
                             "at": event.get("at")})
        elif action == "getBoardMap":
            current = data["board"]
            if board is None or len(current) != len(board):
                raise ValueError("棋盘初始化缺失或尺寸发生变化")
            size = len(board)
            if any(len(row) != size for row in current):
                raise ValueError("棋盘不是方形")
            delta = [(r, c) for r in range(size) for c in range(size)
                     if board[r][c] != current[r][c]]
            if not delta:
                continue  # 失败的落子尝试不计入已生效棋谱。
            if len(delta) != 1:
                errors.append(f"一次棋盘更新改变了 {len(delta)} 格")
                board = [row[:] for row in current]
                continue
            x, y = delta[0]
            field = current[x][y]
            if board[x][y] != 0 or field not in (1, 2):
                errors.append(f"非法棋盘变化: ({x},{y})")
            if field != next_field:
                errors.append(f"第 {len(moves)+1} 手颜色不符合轮流落子")
            brain = next((str(k) for k, v in config["brainsConfig"].items()
                          if v["field"] == field), None) if config else None
            response = responses.pop(brain, {})
            response_ms = response.get("response_ms") if response.get("response") == f"{x} {y}" else None
            moves.append({"ply": len(moves) + 1, "field": field, "row": x, "col": y,
                          "brain_id": brain, "is_mine": brain == my_brain_id,
                          "at": event.get("at"), "server_response_ms": response_ms})
            board = [row[:] for row in current]
            next_field = 3 - field
        elif action == "summary":
            summary = data["data"]
    if config is None or initial is None or summary is None:
        raise ValueError("日志不完整：缺少配置、初始棋盘或结束摘要")
    if board != summary["currentBoard"]:
        errors.append("重放棋盘与日志最终棋盘不一致")
    if errors:
        raise ValueError("; ".join(errors))
    my_field = config["brainsConfig"][my_brain_id]["field"]
    mine_times = [m["server_response_ms"] for m in moves
                  if m["is_mine"] and m["server_response_ms"] is not None]
    return {"initial_board": initial, "moves": moves, "attempted_placements": attempts,
            "final_board": board, "my_field": my_field,
            "round_config": config["roundConfig"], "brains_config": config["brainsConfig"],
            "summary": summary, "exit_reason": summary.get("exitCausedBy"),
            "my_elapsed_ms": summary.get("elapsedRoundTime", {}).get(my_brain_id),
            "my_max_response_ms": max(mine_times, default=None),
            "validation": "replayed_board_matches_log_summary"}


class Client:
    def __init__(self, origin, interval):
        self.origin, self.interval, self.last = origin, interval, 0.0
        self.requests = 0

    def get(self, url):
        if urlsplit(url).netloc != self.origin or urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("拒绝跟随站外链接")
        for attempt in range(3):
            time.sleep(max(0, self.last + self.interval - time.monotonic()))
            self.last = time.monotonic()
            try:
                request = Request(url, headers={"User-Agent": "GomokuPersonalExport/1.0"})
                self.requests += 1
                with urlopen(request, timeout=20) as response:
                    if urlsplit(response.url).netloc != self.origin:
                        raise ValueError("页面重定向到站外")
                    data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError("响应超过 16 MiB")
                return data
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise RuntimeError("平台要求认证；脚本不会绕过权限或读取浏览器凭据") from exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(1 + attempt)


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def text_record(game):
    initial = game["initial_board"]
    lines = [f"比赛: {game['match_id']} / 第 {game['round_number']} 局",
             f"对手: {game['opponent']}", f"己方: {'黑' if game['my_field']==1 else '白'}",
             f"结果（己方视角）: {game['result']}", f"结束原因: {game['exit_reason']}",
             f"原网页: {game['url']}", "坐标: 从 0 开始的 行,列；下列手数不含初始棋子。",
             "初始棋子: " + " ".join(f"{r},{c}:{v}" for r, row in enumerate(initial)
                                     for c, v in enumerate(row) if v), ""]
    for m in game["moves"]:
        lines.append(f"{m['ply']:3d}. {'黑' if m['field']==1 else '白'} "
                     f"{m['row']:2d} {m['col']:2d}  "
                     f"{'己方' if m['is_mine'] else '对手'}  响应={m['server_response_ms']}ms")
    return "\n".join(lines) + "\n"


def pack_archive(output, submission_id, games):
    archive = output.with_name(output.name + "-棋谱.zip")
    archive_temp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(archive_temp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        files = [output / "index.json", output / "summary.md"]
        for game in games:
            rid = game["round_id"]
            files.extend((output / "rounds" / f"{rid}.json", output / "rounds" / f"{rid}.txt",
                          output / "logs" / f"{rid}.jsonl"))
        for path in files:
            z.write(path, f"{submission_id}/{path.relative_to(output).as_posix()}")
    archive_temp.replace(archive)
    return archive


def export(args):
    parsed = urlsplit(args.submission)
    target = re.fullmatch(r"/submission/([a-f0-9]{24})(?:/\d+)?/?", parsed.path)
    if parsed.scheme not in ("http", "https") or not target:
        raise ValueError("请提供 /submission/<24位ID> 格式的提交详情 URL")
    sid = target.group(1)
    base = f"{parsed.scheme}://{parsed.netloc}/submission/{sid}"
    output = Path(args.output).resolve() if args.output else ROOT / "data" / sid
    output.mkdir(parents=True, exist_ok=True)
    client = Client(parsed.netloc, max(0.1, args.interval))
    found, pages, queue = {}, set(), [base]
    while queue:
        url = queue.pop(0)
        if url in pages:
            continue
        pages.add(url)
        matches, links = parse_submission(client.get(url).decode("utf-8"), url, sid)
        found.update((m["match_id"], m) for m in matches)
        queue.extend(link for link in links if link not in pages and link not in queue)
        if len(pages) > 100:
            raise ValueError("分页异常，已停止")
    print(f"发现 {len(pages)} 页、{len(found)} 场关联比赛，开始导出。", flush=True)
    games, errors, pending = [], [], []
    cached_rounds = downloaded_rounds = 0
    for i, match in enumerate(found.values(), 1):
        try:
            rounds = parse_match(client.get(match["url"]).decode("utf-8"), match)
            results = [r["result"] for r in rounds]
            if results and all(s in FINISHED for s in results):
                w, l = results.count("win"), results.count("lose")
                match["result"] = "win" if w > l else "lose" if l > w else "draw"
            match["rounds"] = rounds
        except Exception as exc:
            errors.append({"url": match["url"], "error": str(exc)})
            continue
        for entry in rounds:
            if entry["result"] not in FINISHED:
                pending.append(entry)
                continue
            rid = entry["round_id"]
            record_path = output / "rounds" / f"{rid}.json"
            log_path = output / "logs" / f"{rid}.jsonl"
            try:
                if record_path.exists() and log_path.exists() and not args.refresh:
                    game = json.loads(record_path.read_text(encoding="utf-8"))
                    if (game.get("schema") != SCHEMA or game.get("submission_id") != sid
                            or game.get("result") != entry["result"]):
                        raise ValueError("缓存版本或结果不一致，请使用 --refresh 重新导出")
                    checked = parse_logs(log_path.read_bytes(), game["my_brain_id"])
                    if checked["moves"] != game["moves"] or checked["final_board"] != game["final_board"]:
                        raise ValueError("缓存记录与原始日志不一致，请使用 --refresh")
                    cached_rounds += 1
                else:
                    summary, log_url = parse_round_page(client.get(entry["url"]).decode("utf-8"), entry["url"])
                    raw = client.get(log_url)
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_bytes(raw)  # 即使解析失败，也保留诊断所需的原始日志。
                    content = parse_logs(raw, match["my_brain_id"])
                    if summary.get("currentBoard") != content["final_board"]:
                        raise ValueError("日志重放结果与网页棋盘不一致")
                    game = {"schema": SCHEMA, "submission_id": sid,
                            "match_id": match["match_id"], "opponent": match["opponent"],
                            "opponent_submission_url": match["opponent_submission_url"],
                            "my_brain_id": match["my_brain_id"], **entry, **content,
                            "logs_url": log_url}
                    save_json(record_path, game)
                    downloaded_rounds += 1
                record_path.with_suffix(".txt").write_text(text_record(game), encoding="utf-8")
                games.append(game)
            except Exception as exc:
                errors.append({"url": entry["url"], "error": str(exc)})
        if i % 10 == 0 or i == len(found):
            print(f"已处理 {i}/{len(found)} 场；棋谱 {len(games)} 局；失败 {len(errors)} 项。", flush=True)

    snapshot = {"schema": SCHEMA, "submission_id": sid, "submission_url": base,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "scope": "all matches linked to this submission, including historical opponents",
                "pages": sorted(pages), "match_count": len(found), "round_count": len(games),
                "match_results": dict(Counter(m["result"] for m in found.values())),
                "round_results": dict(Counter(g["result"] for g in games)),
                "by_color": {str(c): dict(Counter(g["result"] for g in games if g["my_field"] == c))
                             for c in (1, 2)},
                "exit_reasons": dict(Counter(g["exit_reason"] for g in games)),
                "pending_rounds": pending, "errors": errors, "http_requests": client.requests,
                "cached_rounds": cached_rounds, "downloaded_rounds": downloaded_rounds,
                "matches": list(found.values()),
                "rounds": [{k: g[k] for k in ("round_id", "match_id", "opponent", "round_number",
                           "result", "my_field", "exit_reason", "my_elapsed_ms", "my_max_response_ms", "url")}
                           | {"move_count": len(g["moves"]), "record": f"rounds/{g['round_id']}.json",
                              "text": f"rounds/{g['round_id']}.txt", "logs": f"logs/{g['round_id']}.jsonl"}
                           for g in games]}
    save_json(output / "index.json", snapshot)
    report = ["# 提交棋谱导出", "", f"提交：{base}",
              f"抓取时间（UTC）：{snapshot['fetched_at']}", "",
              f"共 {len(found)} 场关联比赛，成功导出 {len(games)} 局，待完成 {len(pending)} 局，失败 {len(errors)} 项。",
              f"比赛结果（己方视角）：{snapshot['match_results']}",
              f"单局结果（己方视角）：{snapshot['round_results']}",
              f"执黑：{snapshot['by_color']['1']}；执白：{snapshot['by_color']['2']}",
              f"结束原因：{snapshot['exit_reasons']}", "",
              f"本次复用缓存 {cached_rounds} 局，新下载 {downloaded_rounds} 局。",
              "统计范围是该提交详情页全部关联比赛，包括对手更新版本前后的历史比赛；不一定等于当前排行榜口径。",
              "导出期间平台可能继续增加比赛；再次运行会补抓新局，已保存的完成局默认复用缓存。",
              "JSON 记录可用于后续复盘；TXT 是可读落子序列；logs/ 保存原始 JSONL 日志。",
              "响应耗时来自服务端 TURN 请求和响应的日志时间差，包含调度等开销，不等于精确 CPU 时间。",
              "每份新导出棋谱均校验落子轮换，并重放对照日志摘要和网页最终棋盘。", "",
              "| 对手 | 局 | 己方 | 结果 | 手数 | 棋谱 |", "|---|---:|---|---|---:|---|"]
    for g in games:
        name = g["opponent"].replace("|", "\\|").replace("\n", " ")
        report.append(f"| {name} | {g['round_number']} | {'黑' if g['my_field']==1 else '白'} "
                      f"| {g['result']} | {len(g['moves'])} | [查看](rounds/{g['round_id']}.txt) |")
    if errors:
        report += ["", "## 未成功项目", "", *[f"- {e['url']}：{e['error']}" for e in errors]]
    (output / "summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    archive = pack_archive(output, sid, games)
    print(json.dumps({k: snapshot[k] for k in ("match_count", "round_count", "match_results",
                                              "round_results", "by_color", "exit_reasons")},
                     ensure_ascii=False, indent=2))
    print(f"保存到：{output}", flush=True)
    print(f"打包文件：{archive}", flush=True)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", default=DEFAULT_URL, help="提交详情 URL")
    parser.add_argument("--output", help="输出目录，默认 data/<submission-id>")
    parser.add_argument("--interval", type=float, default=0.25, help="请求最短间隔秒数")
    parser.add_argument("--refresh", action="store_true", help="重新下载已有完成局")
    args = parser.parse_args()
    if not args.submission:
        parser.error("请传入 --submission URL，或在 config/local.json 配置 submission_url")
    try:
        return export(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
