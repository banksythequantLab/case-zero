"""Tests for hypothesis consolidation.

The most important test in this file is the one asserting a merge does NOT
happen. Consolidation that collapses a fraud hypothesis into the innocent
explanation of the same facts would improve every metric we track while
destroying the only thing the architecture is actually for.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from casezero.consolidate import (stance, figures, similarity, should_merge,
                                  merge, consolidate)

# Verbatim from a live run at budget 90. Three incompatible explanations of one
# set of facts - which is what the fleet is supposed to produce.
INNOCENT = ("The identical valuations of $1,170,000 and nearly identical unit counts "
            "(2,853,659 in July 2023 and 2,856,659 in October 2023) across HeadFarm LLC, "
            "CountSharp LLC, CupCrew LLC, and RealWorld LLC are the result of "
            "standardized, templated commercial consulting agreements.")
WRONGDOING = ("The repeating unit counts of 2,853,659 and 2,856,659 and the flat "
              "$1,170,000 valuation across four different clients (HeadFarm LLC, "
              "CountSharp LLC, CupCrew LLC, RealWorld LLC) represent an artificial "
              "revenue generation scheme using predetermined, non-arm's length "
              "valuations to inflate revenues.")
CLERICAL = ("The identical figures of 2,856,659 units and $1,170,000 valuations across "
            "CountSharp LLC, CupCrew LLC, and RealWorld LLC are clerical copy-paste "
            "errors made during preparation of the Form 10-Q.")


class TestStance(unittest.TestCase):
    def test_reads_the_three_live_claims_correctly(self):
        self.assertEqual(stance(WRONGDOING), "ASSERTS_WRONGDOING")
        self.assertEqual(stance(INNOCENT), "ASSERTS_INNOCENT")
        self.assertEqual(stance(CLERICAL), "ASSERTS_INNOCENT")

    def test_unmarked_claim_is_neutral(self):
        self.assertEqual(stance("Revenue for the period was $8,493,985."), "NEUTRAL")

    def test_mixed_signals_without_a_clear_margin_are_ambiguous(self):
        """Two accusation words against one exoneration word is not a stance.
        Reading it as an accusation on a 2-1 count, then merging on that, is the
        confident guess this module must not make."""
        self.assertEqual(stance("The standard practice was an artificial scheme."),
                         "AMBIGUOUS")

    def test_an_ambiguous_claim_merges_with_nothing_not_even_itself(self):
        a = {"claim": "The standard $1,170,000 practice was an artificial scheme."}
        ok, why = should_merge(a, dict(a))
        self.assertFalse(ok)
        self.assertIn("unreadable", why)


class TestFigures(unittest.TestCase):
    def test_currency_and_bare_forms_are_one_figure(self):
        self.assertEqual(figures("$1,170,000"), figures("1,170,000"))

    def test_small_integers_are_not_identity_bearing(self):
        """Years and counts-of-parties would otherwise match everything."""
        self.assertEqual(figures("across 4 clients in 2023"), set())

    def test_extracts_the_live_fingerprint(self):
        self.assertEqual(figures(WRONGDOING), {"2853659", "2856659", "1170000"})


class TestShouldMerge(unittest.TestCase):
    def test_NEVER_merges_across_stance(self):
        """THE test. These two claims share every figure and every entity and
        are 'about' exactly the same thing. They are the fraud reading and the
        innocent reading of one fact pattern. Merging them would delete the
        disagreement the fleet exists to produce, and it would look like an
        improvement on every metric we track."""
        a = {"id": "H-1", "claim": WRONGDOING, "confidence": 0.35}
        b = {"id": "H-2", "claim": INNOCENT, "confidence": 0.55}
        ok, why = should_merge(a, b)
        self.assertFalse(ok)
        self.assertIn("stance", why)

    def test_never_merges_two_rival_innocent_explanations_with_wrongdoing(self):
        for other in (INNOCENT, CLERICAL):
            ok, _ = should_merge({"claim": WRONGDOING}, {"claim": other})
            self.assertFalse(ok)

    def test_requires_shared_figures_not_just_a_shared_topic(self):
        a = {"claim": "Revenue of $1,170,000 was artificially inflated by the scheme."}
        b = {"claim": "Revenue of $9,999,999 was artificially inflated by the scheme."}
        ok, why = should_merge(a, b)
        self.assertFalse(ok)
        self.assertIn("shared figures", why)

    def test_merges_a_genuine_same_stance_restatement(self):
        a = {"id": "H-1", "confidence": 0.4,
             "claim": "The repeated $1,170,000 valuations across CountSharp LLC and "
                      "CupCrew LLC represent an artificial revenue scheme with "
                      "non-arm's length valuations used to inflate revenues."}
        b = {"id": "H-2", "confidence": 0.3,
             "claim": "The repeated $1,170,000 valuations across CountSharp LLC and "
                      "CupCrew LLC are an artificial scheme, using non-arm's length "
                      "valuations to inflate reported revenues."}
        ok, why = should_merge(a, b)
        self.assertTrue(ok, why)
        self.assertIn("same stance", why)


class TestMerge(unittest.TestCase):
    def test_confidence_is_max_never_a_sum_or_a_boost(self):
        """Two phrasings from one model over one corpus are not independent
        measurements. Adding them would manufacture certainty from repetition."""
        out = merge({"id": "A", "confidence": 0.4}, {"id": "B", "confidence": 0.3})
        self.assertEqual(out["confidence"], 0.4)
        out = merge({"id": "A", "confidence": 0.3}, {"id": "B", "confidence": 0.4})
        self.assertEqual(out["confidence"], 0.4)

    def test_supporting_evidence_pools_and_deduplicates(self):
        out = merge({"id": "A", "supporting": ["E-1", "E-2"]},
                    {"id": "B", "supporting": ["E-2", "E-3"]})
        self.assertEqual(sorted(out["supporting"]), ["E-1", "E-2", "E-3"])

    def test_the_absorbed_claim_is_recorded_verbatim(self):
        """A consolidation that cannot be read back and disputed is just quiet
        deletion."""
        out = merge({"id": "A"}, {"id": "B", "claim": "absorbed text", "confidence": 0.3})
        self.assertEqual(out["merged_from"][0]["id"], "B")
        self.assertEqual(out["merged_from"][0]["claim"], "absorbed text")

    def test_missing_confidence_does_not_crash(self):
        self.assertNotIn("confidence", merge({"id": "A"}, {"id": "B"}))


class TestConsolidate(unittest.TestCase):
    def test_the_three_live_claims_all_survive(self):
        hyps = [{"id": "H-w", "claim": WRONGDOING, "confidence": 0.35},
                {"id": "H-i", "claim": INNOCENT, "confidence": 0.55},
                {"id": "H-c", "claim": CLERICAL, "confidence": 0.20}]
        kept, log = consolidate(hyps)
        self.assertEqual(len(kept), 3, "competing explanations must all survive")
        self.assertEqual(log, [])

    def test_highest_confidence_member_becomes_canonical(self):
        a = {"id": "H-lo", "confidence": 0.3,
             "claim": "The repeated $1,170,000 valuations across CountSharp LLC are an "
                      "artificial scheme using non-arm's length valuations to inflate."}
        b = {"id": "H-hi", "confidence": 0.6,
             "claim": "The repeated $1,170,000 valuations across CountSharp LLC "
                      "represent an artificial scheme with non-arm's length valuations "
                      "used to inflate revenues."}
        kept, log = consolidate([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], "H-hi")
        self.assertEqual(kept[0]["confidence"], 0.6)
        self.assertEqual(log[0]["absorbed"], "H-lo")

    def test_empty_input(self):
        self.assertEqual(consolidate([]), ([], []))


class TestAgainstRealRunOutput(unittest.TestCase):
    """The negative result, pinned so it cannot quietly change.

    We predicted the fleet was fragmenting one finding across several weak
    hypotheses, built this module to merge them, and measured: across 56
    hypothesis pairs from six live runs, ZERO merge. The claims are distinct -
    different stances, different scopes - not duplicates. The diagnosis was
    wrong, and the module is a safety net that has never had to catch anything.

    If a future change makes this fire on real output, that is worth knowing
    deliberately rather than discovering it in a demo.
    """
    def test_the_full_live_set_produces_no_merges(self):
        hyps = [{"id": "H-1", "claim": WRONGDOING, "confidence": 0.35},
                {"id": "H-2", "claim": INNOCENT, "confidence": 0.55},
                {"id": "H-3", "claim": CLERICAL, "confidence": 0.20},
                {"id": "H-4", "confidence": 0.30,
                 "claim": "Netcapital Inc. artificially inflated its reported revenues "
                          "and profitability by recording non-cash consulting services "
                          "paid in highly illiquid, overvalued equity units of its own "
                          "crowdfunding clients."},
                {"id": "H-5", "confidence": 0.70,
                 "claim": "Netcapital Inc. determined the fair value of its equity "
                          "investments based primarily on the most recent public "
                          "offering price of campaigns hosted on its own platform."}]
        kept, log = consolidate(hyps)
        self.assertEqual(len(kept), 5, f"unexpected merges: {log}")
        self.assertEqual(log, [])

    def test_the_two_wrongdoing_claims_are_not_duplicates(self):
        """H-1 is specific to four named clients; H-4 is a broader claim that
        subsumes it. Lexical similarity 0.09, zero shared figures."""
        broad = ("Netcapital Inc. artificially inflated its reported revenues and "
                 "profitability by recording non-cash consulting services paid in "
                 "highly illiquid, overvalued equity units.")
        self.assertEqual(stance(WRONGDOING), stance(broad))
        self.assertLess(similarity(WRONGDOING, broad), 0.2)
        self.assertFalse(should_merge({"claim": WRONGDOING}, {"claim": broad})[0])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad}/{result.testsRun} passed")
    sys.exit(1 if bad else 0)
