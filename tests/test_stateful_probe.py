#!/usr/bin/env python3
"""Short I/O parity with production protocol; no arena or timing-dependent move assertion."""
import argparse
import json
import pathlib
import select
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Pipe:
    def __init__(self, executable):
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def send(self, text):
        self.process.stdin.write((text + '\n').encode())
        self.process.stdin.flush()

    def read(self):
        deadline = time.monotonic() + 5
        data = bytearray()
        while not data.endswith(b'\n'):
            left = deadline - time.monotonic()
            assert left > 0 and select.select([self.process.stdout], [], [], left)[0], 'response timeout'
            chunk = self.process.stdout.read(1)
            assert chunk, 'unexpected EOF'
            data.extend(chunk)
        return data.decode().strip()

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        assert self.process.returncode == 0, self.process.stderr.read().decode()
        assert not self.process.stdout.read()
        assert not self.process.stderr.read()


def opening():
    b = [[0] * 12 for _ in range(12)]
    for r, c, s in [(5, 6, 1), (5, 5, 2), (6, 5, 1), (6, 6, 2)]:
        b[r][c] = s
    return b


def query(probe, board, side, ms=-1):
    probe.send(f's {side} {ms} ' + ' '.join(map(str, sum(board, []))))
    return json.loads(probe.read())


def validate_carry(results):
    for i, row in enumerate(results):
        assert row['turn'] == i + 1
        assert row['used_seconds'] >= row['used_seconds_before'] >= 0
        if i:
            assert row['used_seconds_before'] == results[i-1]['used_seconds']
            assert row['history_before'] == results[i-1]['history_after']
            assert row['generation'] == (results[i-1]['generation'] + 1) % 256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', default=str(ROOT/'build/release/probe_stateful'))
    parser.add_argument('--protocol', default=str(ROOT/'build/release/brain'))
    parser.add_argument('--output', default=str(ROOT/'build/release/stateful_validation.json'))
    args = parser.parse_args()
    cases = []

    fixtures = json.loads((ROOT/'tests/fixtures/stateful_positions.json').read_text())
    # These short prefixes are book hits in the current release, so this
    # comparison does not assert a time-sensitive searched move is reproducible.
    for game in fixtures['book_prefixes']:
        own_turns = game['own_turns']
        protocol, probe = Pipe(args.protocol), Pipe(args.probe)
        board = opening()
        side = game['side']
        protocol.send(f'START {side}')
        assert protocol.read() == 'OK'
        results = []
        for move in game['moves']:
            if move['is_mine']:
                protocol.send('TURN')
                r, c = map(int, protocol.read().split())
                actual = query(probe, board, side)
                assert actual['pos'] == r * 12 + c == move['row'] * 12 + move['col']
                assert actual['depth'] == 0 and actual['nodes'] == 0
                results.append(actual)
                board[r][c] = side
                if len(results) == own_turns:
                    break
            else:
                protocol.send(f"PLACE {move['row']} {move['col']}")
                board[move['row']][move['col']] = 3 - side
        validate_carry(results)
        protocol.send('END 0')
        protocol.close()
        probe.close()
        cases.append(dict(kind='recorded_book_prefix',side=side,turns=len(results),results=results))

    # Staged protocol fixture: multiple PLACE commands create horizontal fours.
    # It checks protocol state/priority, not a legal alternating-turn match.
    protocol, probe = Pipe(args.protocol), Pipe(args.probe)
    protocol.send('START 1')
    assert protocol.read() == 'OK'
    board, results = opening(), []
    for row in range(4):
        for col in range(4):
            protocol.send(f'PLACE {row} {col}')
            board[row][col] = 2
        protocol.send('TURN')
        r, c = map(int, protocol.read().split())
        actual = query(probe, board, 1, 0)
        assert actual['pos'] == r * 12 + c == row * 12 + 4
        board[r][c] = 1
        results.append(actual)
    # With both sides threatening, the current side's immediate five wins first.
    protocol.send('TURN')
    r, c = map(int, protocol.read().split())
    actual = query(probe, board, 1, 0)
    assert actual['pos'] == r * 12 + c == 52
    results.append(actual)
    validate_carry(results)
    protocol.send('END 0')
    protocol.close()
    probe.close()
    cases.append(dict(kind='staged_four_blocks_then_immediate_win',turns=5,results=results))

    # A brief searched position creates nonzero history. Re-submit a board with
    # zero time to test that replacing Board did not recreate/reset Engine.
    regression = fixtures['history_position']
    probe = Pipe(args.probe)
    first = query(probe, regression['board'], regression['side'], 80)
    assert first['nodes'] > 0 and first['history_nonzero'] > 0
    second = query(probe, regression['board'], regression['side'], 0)
    validate_carry([first, second])
    assert second['history_nonzero'] > 0
    probe.close()
    cases.append(dict(kind='nonzero_history_and_timer_survive_board_rebuild',results=[first,second]))

    report = dict(probe=args.probe,protocol=args.protocol,protocol_move_comparisons=10,
                  passed=True,cases=cases,
                  limitation='Parity uses deterministic book/forcing paths. Staged tactical fixture is not an alternating-turn match. No full arena or timing-sensitive search-move parity claim.')
    pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('PASS: 10 production/stateful move comparisons; both colors; actual history and cumulative timer persist across Board rebuild')


if __name__ == '__main__':
    main()
