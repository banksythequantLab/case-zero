"""Tests for passage selection.

The regression at the bottom is the one that matters: it pins the exact bug that
made every live run structurally incapable of seeing the central evidence.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from casezero.passages import (query_terms, find_spans, select, score_document,
                               HEAD_CHARS)

NEEDLE = ("In April 2023, the Company received 2,853,659 units of HeadFarm LLC as a "
          "payment for services rendered in conjunction with a crowdfunding offering.")


def doc(needle_at: int, total: int = 320_000) -> str:
    """A document with the interesting sentence buried deep, like a real 10-K."""
    filler = "Filler sentence about general corporate matters. "
    head = "ANNUAL REPORT FORM 10-K Netcapital Inc. fiscal year ended April 30, 2023. "
    body = head + (filler * ((needle_at - len(head)) // len(filler) + 1))[:needle_at - len(head)]
    body += NEEDLE
    body += (filler * ((total - len(body)) // len(filler) + 1))[:max(0, total - len(body))]
    return body


class TestQueryTerms(unittest.TestCase):
    def test_figures_come_first(self):
        t = query_terms("find the revenue figure 2,853,659 in the filings")
        self.assertEqual(t[0], "2,853,659")

    def test_stopwords_dropped(self):
        self.assertNotIn("company", query_terms("the company reported revenue"))

    def test_extra_selectors_are_accepted(self):
        self.assertIn("1,170,000", query_terms("revenue", extra=["1,170,000"]))

    def test_deduplicates(self):
        t = query_terms("revenue revenue 2,853,659 2,853,659")
        self.assertEqual(t.count("2,853,659"), 1)
        self.assertEqual(t.count("revenue"), 1)


class TestFindSpans(unittest.TestCase):
    def test_searches_the_whole_text_not_the_head(self):
        text = doc(needle_at=300_000)
        spans = find_spans(text, ["2,853,659"])
        self.assertTrue(spans)
        self.assertGreater(spans[0][0], 250_000)

    def test_short_terms_are_ignored(self):
        self.assertEqual(find_spans("abc abc abc", ["abc"]), [])


class TestSelect(unittest.TestCase):
    def test_short_document_returned_whole(self):
        out, st = select("a short filing", ["filing"], budget=40_000)
        self.assertEqual(out, "a short filing")
        self.assertEqual(st["mode"], "full")

    def test_no_match_falls_back_to_the_head(self):
        text = doc(needle_at=300_000)
        out, st = select(text, ["nonexistentterm"], budget=10_000)
        self.assertEqual(st["mode"], "head")
        self.assertEqual(len(out), 10_000)

    def test_respects_the_budget(self):
        text = doc(needle_at=300_000)
        _, st = select(text, ["2,853,659"], budget=20_000)
        self.assertLessEqual(st["chars"], 20_000)

    def test_head_is_always_included_so_the_filing_is_identifiable(self):
        text = doc(needle_at=300_000)
        out, _ = select(text, ["2,853,659"], budget=40_000)
        self.assertIn("FORM 10-K", out)

    def test_elisions_are_marked(self):
        """An agent that cannot tell truncated text from complete text keeps
        concluding things are absent - which is exactly the failure we spent a
        day mis-diagnosing as hallucination."""
        text = doc(needle_at=300_000)
        out, _ = select(text, ["2,853,659"], budget=40_000)
        self.assertIn("characters omitted", out)

    def test_denser_windows_win_a_tight_budget(self):
        text = ("HEADER. " + "x " * 5_000 + "alpha filler alpha filler alpha. "
                + "y " * 5_000 + "alpha alone here. " + "z " * 5_000)
        out, _ = select(text, ["alpha"], budget=3_000, window=200, head=20)
        self.assertIn("alpha filler alpha filler alpha", out)


class TestScoreDocument(unittest.TestCase):
    def test_counts_over_the_whole_document(self):
        """Scoring on read(8000) ranked filings by their cover page."""
        text = doc(needle_at=300_000)
        self.assertGreater(score_document(text, ["2,853,659"]), 0)

    def test_ranks_the_document_that_contains_the_answer_highest(self):
        has = doc(needle_at=300_000)
        hasnt = doc(needle_at=300_000).replace("2,853,659", "9,999,999")
        self.assertGreater(score_document(has, ["2,853,659"]),
                           score_document(hasnt, ["2,853,659"]))


class TestTheHeadCutRegression(unittest.TestCase):
    """THE regression.

    In the real FY2023 10-K (320,968 chars) the sentence naming 2,853,659 begins
    at character 302,971. The dispatcher sent `read()[:40000]`. The fleet was
    therefore structurally incapable of seeing the central evidence in ANY run,
    at ANY budget — and when it reported "verbatim sentences containing
    2,853,659 cannot be extracted... the text is truncated after Note 3" it was
    describing its context window accurately. We logged that as a hallucination.
    It was not.
    """
    def setUp(self):
        self.text = doc(needle_at=302_971, total=320_968)

    def test_the_old_head_cut_could_not_see_it(self):
        self.assertNotIn("2,853,659", self.text[:40_000])

    def test_windowed_selection_at_the_same_budget_does(self):
        out, st = select(self.text, query_terms("figures repeating across parties",
                                                extra=["2,853,659"]), budget=40_000)
        self.assertIn("2,853,659", out)
        self.assertIn("HeadFarm LLC", out)
        self.assertLessEqual(st["chars"], 40_000)

    def test_the_surrounding_sentence_survives_intact(self):
        """A citation is only verifiable if the whole sentence is present."""
        out, _ = select(self.text, ["2,853,659"], budget=40_000)
        self.assertIn(NEEDLE, out)


@unittest.skipUnless(os.path.isfile("corpus/2023-07-26_10-K_000560.txt"),
                     "corpus not present")
class TestAgainstTheRealFiling(unittest.TestCase):
    def setUp(self):
        with open("corpus/2023-07-26_10-K_000560.txt", errors="replace") as fh:
            self.text = fh.read()

    def test_the_decisive_figure_really_is_beyond_the_old_cut(self):
        self.assertGreater(self.text.find("2,853,659"), 300_000)
        self.assertNotIn("2,853,659", self.text[:40_000])

    def test_windowed_selection_reaches_the_investments_note(self):
        terms = query_terms("revenue composition and figures repeating across "
                            "supposedly independent parties",
                            extra=["2,853,659", "1,170,000"])
        out, st = select(self.text, terms, budget=40_000)
        for needle in ("2,853,659", "1,170,000", "HeadFarm LLC", "CountSharp LLC"):
            self.assertIn(needle, out, needle)
        self.assertEqual(st["mode"], "windows")
        self.assertLessEqual(st["chars"], 40_000)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad}/{result.testsRun} passed")
    sys.exit(1 if bad else 0)
