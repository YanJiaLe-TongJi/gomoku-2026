import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("export_games", Path(__file__).parents[1] / "scripts/export_games.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def fixture():
    initial = [[0] * 5 for _ in range(5)]
    final = copy.deepcopy(initial)
    final[1][2] = 2
    events = [
        {"at": 0, "data": {"action": "initialize", "roundConfig": {"size": 5},
                            "brainsConfig": {"0": {"field": 2}, "1": {"field": 1}}}},
        {"at": 1, "data": {"action": "clearBoard", "board": initial, "nextField": 2}},
        {"at": 10, "data": {"action": "sendRequest", "id": "0", "data": "TURN"}},
        {"at": 110, "data": {"action": "receiveResponse", "id": "0", "data": "1 2"}},
        {"at": 111, "data": {"action": "place", "field": 2, "position": "1 2"}},
        {"at": 112, "data": {"action": "getBoardMap", "board": final}},
        {"at": 120, "data": {"action": "summary", "data": {
            "elapsedRoundTime": {"0": 100, "1": 0}, "exitCausedBy": "test",
            "currentBoard": final, "roundConfig": {"size": 5}}}},
    ]
    return events


def encoded(events):
    return "\n".join(json.dumps(e) for e in events).encode()


class ExportTests(unittest.TestCase):
    def test_color_not_inferred_from_round_number(self):
        result = exporter.parse_logs(encoded(fixture()), "0")
        self.assertEqual(result["my_field"], 2)
        self.assertEqual(len(result["moves"]), 1)
        self.assertTrue(result["moves"][0]["is_mine"])
        self.assertEqual(result["moves"][0]["server_response_ms"], 100)

    def test_failed_attempt_not_a_move(self):
        events = fixture()
        events.insert(-1, {"at": 115, "data": {"action": "place", "field": 1, "position": "99 99"}})
        result = exporter.parse_logs(encoded(events), "0")
        self.assertEqual(len(result["attempted_placements"]), 2)
        self.assertEqual(len(result["moves"]), 1)

    def test_incomplete_log_is_not_success(self):
        with self.assertRaisesRegex(ValueError, "日志不完整"):
            exporter.parse_logs(encoded(fixture()[:-1]), "0")

    def test_wrong_final_board_is_not_success(self):
        events = fixture()
        events[-1]["data"]["data"]["currentBoard"] = [[0] * 5 for _ in range(5)]
        with self.assertRaisesRegex(ValueError, "最终棋盘不一致"):
            exporter.parse_logs(encoded(events), "0")

    def test_round_results_use_submitter_column(self):
        source = '''<tbody id="round_row_container"><tr>
        <td class="col--round-no">#2</td>
        <td class="col--challenger"><span class="round-status--text win">Win</span></td>
        <td class="col--challengee"><span class="round-status--text lose">Lose</span></td>
        <td><a href="/match/m/round/r">View Board</a></td></tr></tbody>'''
        result = exporter.parse_match(source, {"url": "http://example.test/match/m", "my_brain_id": "1"})
        self.assertEqual(result[0]["result"], "lose")
        self.assertEqual(result[0]["round_number"], 2)


if __name__ == "__main__":
    unittest.main()
