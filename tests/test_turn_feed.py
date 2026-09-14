"""The turn feed is a raw-JSON channel, so leakage is the whole risk.

These tests are the audit: they assert that nothing a seat may not know can
reach another seat's prompt, both at the unit level (the allow-list) and
end-to-end (scanning every prompt a full mock match actually produced).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from turn_feed import TurnFeed, PUBLIC_FIELDS

CARD_RE = re.compile(
    r"\b(as|dos|tres|cuatro|cinco|seis|siete|sota|caballo|rey) "
    r"de (oros|copas|espadas|bastos)\b")

SECRET_ACTION = {
    "action": "envido",
    "message": "Vamos alla",
    "thought": "SECRET-REASONING I am bluffing with nothing",
    "cards": ["rey de oros", "rey de copas"],
    "signal": "muerde-el-labio-inferior",
    "signal_policy": {"rules": [{"gesture": "guinar-el-ojo"}]},
    "read": {"p_win_lance": 0.81},
}


def feed_with_secret():
    f = TurnFeed()
    f.record(turn=1, hand=1, seat=0, phase="ENVITE", lance="Grande",
             action=SECRET_ACTION, thought=SECRET_ACTION["thought"])
    return f


class AllowListTest(unittest.TestCase):
    def test_table_view_hides_thought_cards_signal_and_read(self):
        view = feed_with_secret().view_for(1)[0]
        blob = json.dumps(view)
        for secret in ("SECRET-REASONING", "rey de oros", "rey de copas",
                       "muerde-el-labio-inferior", "guinar-el-ojo",
                       "p_win_lance"):
            self.assertNotIn(secret, blob)
        self.assertEqual(view["action"], "envido")
        self.assertEqual(view["message"], "Vamos alla")

    def test_discards_show_a_count_never_the_cards(self):
        view = feed_with_secret().view_for(1)[0]
        self.assertEqual(view["discarded"], 2)

    def test_own_view_keeps_only_its_own_thought(self):
        view = feed_with_secret().view_for(0)[0]
        self.assertIn("SECRET-REASONING", view["thought"])
        self.assertNotIn("rey de oros", json.dumps(view))

    def test_a_new_action_field_is_private_by_default(self):
        """The view is built from an allow-list, so a field added to the
        action schema tomorrow cannot leak by being forgotten."""
        f = TurnFeed()
        f.record(turn=1, hand=1, seat=0, phase="ENVITE", lance="Grande",
                 action=dict(SECRET_ACTION, brand_new_field="LEAK"))
        self.assertNotIn("LEAK", json.dumps(f.view_for(1)))
        self.assertNotIn("LEAK", json.dumps(f.view_for(0)))
        for key in f.view_for(1)[0]:
            self.assertIn(key, PUBLIC_FIELDS)

    def test_a_vaca_clears_the_feed(self):
        f = feed_with_secret()
        self.assertEqual(len(f.view_for(1)), 1)
        f.reset(vaca=1)
        self.assertEqual(f.view_for(1), [])
        self.assertEqual(f.vaca, 1)

    def test_feed_is_capped(self):
        f = TurnFeed(limit=5)
        for t in range(50):
            f.record(turn=t, hand=1, seat=t % 4, phase="ENVITE",
                     lance="Grande", action={"action": "paso"})
        self.assertEqual(len(f.view_for(0)), 5)
        self.assertLess(len(f.turns), 50)          # memory stays bounded


class EndToEndLeakTest(unittest.TestCase):
    """Scan every prompt a real mock match produced."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = subprocess.run(
            [sys.executable, "run_mock_match.py", "--hands", "10",
             "--seed", "6", "--turn-feed", "--memory", "notes",
             "--out", cls.tmp.name],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assert r.returncode == 0, r.stderr[-2000:]
        with open(os.path.join(cls.tmp.name, "io.jsonl"), encoding="utf8") as f:
            cls.rows = [json.loads(l) for l in f]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_run_actually_exercised_the_feed(self):
        self.assertGreater(len(self.rows), 100)
        self.assertTrue(any("TURN FEED" in r["prompt"] for r in self.rows))
        self.assertTrue(any(r["phase"] == "VACA_NOTE" for r in self.rows))

    def test_no_prompt_contains_a_card_the_seat_does_not_hold(self):
        """Every card named anywhere in a prompt must be one of the four in
        that seat's own hand. This is the decisive check: cards are unique in
        the deck, so any other seat's card appearing is a hard leak."""
        checked = 0
        for row in self.rows:
            prompt = row["prompt"]
            m = re.search(r"YOUR HAND: (.+?)\s+\(punto", prompt)
            if not m:
                continue                    # e.g. the vaca-note prompt
            own = set(CARD_RE.findall(m.group(1)))
            found = set(CARD_RE.findall(prompt))
            self.assertTrue(found <= own,
                            f"seat {row['seat']} prompt leaked "
                            f"{sorted(found - own)}")
            checked += 1
        self.assertGreater(checked, 50)

    def test_the_vaca_note_prompt_names_no_cards_at_all(self):
        notes = [r for r in self.rows if r["phase"] == "VACA_NOTE"]
        self.assertTrue(notes)
        for row in notes:
            self.assertEqual(CARD_RE.findall(row["prompt"]), [])

    def test_no_prompt_carries_another_seats_private_thought(self):
        """A seat's own thought may come back to it; nobody else's may."""
        thoughts = {}
        for row in self.rows:
            action = row.get("action") or {}
            t = action.get("thought")
            if isinstance(t, str) and t.strip():
                thoughts.setdefault(row["seat"], set()).add(t.strip())
        self.assertTrue(thoughts)
        leaks = 0
        for row in self.rows:
            for seat, texts in thoughts.items():
                if seat == row["seat"]:
                    continue
                for t in texts:
                    if len(t) > 25 and t in row["prompt"]:
                        leaks += 1
        self.assertEqual(leaks, 0)


if __name__ == "__main__":
    unittest.main()
