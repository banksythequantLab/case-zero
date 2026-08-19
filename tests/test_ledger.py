"""Tests for the deterministic forensic-accountant pass.

Everything except the last class runs on synthetic fixtures in a temp directory,
so the suite stays offline and corpus-independent. Several fixtures are
regressions for failures that actually shipped - the comments name them, because
a test whose motivation is lost gets deleted by the next person who finds it
inconvenient.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import tempfile
import unittest

from casezero import ledger


def _corpus(**files) -> str:
    d = tempfile.mkdtemp()
    for name, body in files.items():
        with open(os.path.join(d, f"{name.replace('_', '-')}.txt"), "w") as fh:
            fh.write(body)
    return d


# Shaped like the real Investments note: entity named once, figures trailing
# several hard-wrapped lines later.
DEAL = """In April 2023, the Company received {units} units
of {name} as a payment for services rendered in conjunction with a crowdfunding
offering. The units are valued at ${px} per unit based on a sales price of ${px}
per unit. The receipt of the units satisfied an accounts receivable balance
of ${amount}.

"""


def deal(name, units="2,853,659", amount="1,170,000", px="0.41"):
    return DEAL.format(name=name, units=units, amount=amount, px=px)


def cash_deal(name, amount="40,000"):
    return (f"In August 2020 the Company entered a consulting agreement with {name}\n"
            f"for a ${amount} fee over a 12-month period.\n\n")


def conc(period, pairs):
    body = f"For the {period}, the Company had "
    body += ", ".join(f"one customer, {n} that constituted {p}% of revenues"
                      for n, p in pairs)
    return body + ".\n\n"


RATE = ("The Netcapital funding portal charges a $5,000 to $10,000 engagement fee "
        "and a 4.9% success fee for capital raised at closing.\n\n")


class TestEngagementRegister(unittest.TestCase):
    def test_extracts_equity_engagements(self):
        d = _corpus(a=deal("Alpha LLC"), b=deal("Bravo LLC"))
        reg = ledger.engagement_register(d)
        parties = {r["counterparty"] for r in reg["equity"]}
        self.assertEqual(parties, {"Alpha LLC", "Bravo LLC"})
        row = next(r for r in reg["equity"] if r["counterparty"] == "Alpha LLC")
        self.assertEqual(row["consideration"], 1170000.0)
        self.assertEqual(row["units"], 2853659.0)
        self.assertEqual(row["unit_price"], 0.41)
        self.assertEqual(row["settled_in"], "counterparty equity")

    def test_restatement_across_filings_is_one_engagement(self):
        """The same deal is restated in every later filing. Counting each
        restatement would multiply the company's revenue by the number of
        filings that mention it."""
        body = deal("Alpha LLC")
        d = _corpus(**{"2022-01-01_10-Q_1": body, "2022-04-01_10-Q_2": body,
                       "2022-07-01_10-K_3": body})
        reg = ledger.engagement_register(d)
        self.assertEqual(len(reg["equity"]), 1)
        self.assertEqual(reg["equity"][0]["consideration"], 1170000.0)
        self.assertEqual(reg["equity"][0]["filing_count"], 3)
        self.assertEqual(reg["equity"][0]["first_disclosed"], "2022-01-01")

    def test_cash_engagements_are_a_separate_bucket(self):
        d = _corpus(a=deal("Alpha LLC") + cash_deal("Vymedic, Inc."),
                    b=deal("Alpha LLC") + cash_deal("Vymedic, Inc."))
        reg = ledger.engagement_register(d)
        self.assertEqual([r["counterparty"] for r in reg["cash"]], ["Vymedic, Inc"])
        self.assertEqual(reg["cash"][0]["consideration"], 40000.0)
        self.assertNotIn("Vymedic, Inc", {r["counterparty"] for r in reg["equity"]})

    def test_the_filer_is_never_a_counterparty(self):
        d = _corpus(a=deal("Netcapital Advisors Inc") + deal("Alpha LLC"),
                    b=deal("Alpha LLC"))
        reg = ledger.engagement_register(d)
        self.assertEqual({r["counterparty"] for r in reg["equity"]}, {"Alpha LLC"})

    def test_receivable_amount_is_not_truncated(self):
        """A too-small search window once clipped '712,500' to '712,50',
        silently under-reporting the engagement by a factor of ten."""
        d = _corpus(a=deal("Alpha LLC", amount="712,500"))
        reg = ledger.engagement_register(d)
        self.assertEqual(reg["equity"][0]["consideration"], 712500.0)


class TestConcentration(unittest.TestCase):
    def test_reads_disclosed_customer_shares(self):
        body = conc("three-month period ended July 31, 2023",
                    [("AceHedge LLC", 37), ("Fantize LLC", 37)])
        d = _corpus(a=body, b=body)
        c = ledger.concentration(d)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["named_share_pct"], 74)
        self.assertEqual({x["counterparty"] for x in c[0]["customers"]},
                         {"AceHedge LLC", "Fantize LLC"})

    def test_reaches_customers_the_register_never_sees(self):
        """The Investments note describes equity deals; the concentration table
        names customers whose deals it never describes. Only the union is the
        customer base."""
        d = _corpus(a=deal("Alpha LLC") + conc("three-month period ended July 31, 2023",
                                               [("Zulu LLC", 37)]),
                    b=deal("Alpha LLC"))
        reg = ledger.engagement_register(d)
        names = ledger.counterparty_set(reg, ledger.concentration(d))
        self.assertIn("Alpha LLC", names)
        self.assertIn("Zulu LLC", names)


class TestValueConcentration(unittest.TestCase):
    QUARTERS = [{"start": "2023-05-01", "end": "2023-07-31", "revenue": 1_000_000},
                {"start": "2023-08-01", "end": "2023-10-31", "revenue": 3_000_000}]

    def test_multiplies_percentage_by_window_revenue(self):
        c = [{"period": "six-month period ended October 31, 2023",
              "customers": [{"counterparty": "AceHedge LLC", "pct": 25}],
              "named_share_pct": 25}]
        got = ledger.value_concentration(c, self.QUARTERS)
        self.assertEqual(got["customers"][0]["value"], 1_000_000)   # 25% of 4M
        self.assertEqual(got["total"], 1_000_000)

    def test_longest_window_supersedes_the_shorter_one(self):
        """A six-month disclosure CONTAINS the three-month one. Adding both
        double-counts the first quarter."""
        c = [{"period": "three-month period ended July 31, 2023",
              "customers": [{"counterparty": "AceHedge LLC", "pct": 50}],
              "named_share_pct": 50},
             {"period": "six-month period ended October 31, 2023",
              "customers": [{"counterparty": "AceHedge LLC", "pct": 25}],
              "named_share_pct": 25}]
        got = ledger.value_concentration(c, self.QUARTERS)
        self.assertEqual(len(got["customers"]), 1)
        self.assertEqual(got["customers"][0]["months"], 6)
        self.assertEqual(got["total"], 1_000_000)

    def test_no_revenue_means_no_derivation(self):
        c = [{"period": "six-month period ended October 31, 2023",
              "customers": [{"counterparty": "A LLC", "pct": 25}], "named_share_pct": 25}]
        self.assertEqual(ledger.value_concentration(c, [])["total"], 0.0)

    def test_window_outside_the_reported_quarters_is_skipped(self):
        c = [{"period": "six-month period ended December 31, 2029",
              "customers": [{"counterparty": "A LLC", "pct": 25}], "named_share_pct": 25}]
        self.assertEqual(ledger.value_concentration(c, self.QUARTERS)["total"], 0.0)


class TestReconciliation(unittest.TestCase):
    def _reg(self):
        d = _corpus(a=deal("Alpha LLC") + deal("Bravo LLC", amount="2,100,000")
                      + cash_deal("Vymedic, Inc."),
                    b=deal("Alpha LLC"))
        return ledger.engagement_register(d)

    def test_totals_and_shares(self):
        rec = ledger.reconcile(self._reg(), reported_revenue=10_000_000,
                               window=["2021-10-01", "2024-01-31"])
        self.assertEqual(rec["equity_total"], 3_270_000)
        self.assertEqual(rec["equity_counterparties"], 2)
        self.assertEqual(rec["cash_total"], 40_000)
        self.assertEqual(rec["equity_share_pct"], 32.7)

    def test_derived_is_added_but_reported_separately(self):
        """Merging disclosed dollars with derived ones hides which half rests on
        an inference."""
        derived = {"customers": [{"counterparty": "Zulu LLC"}], "total": 730_000.0}
        rec = ledger.reconcile(self._reg(), 10_000_000, ["a", "b"], derived)
        self.assertEqual(rec["equity_total"], 3_270_000)      # unchanged
        self.assertEqual(rec["derived_total"], 730_000)
        self.assertEqual(rec["attributed_total"], 4_000_000)
        self.assertEqual(rec["attributed_share_pct"], 40.0)

    def test_overstatement_of_the_remainder(self):
        rec = ledger.reconcile(self._reg(), 10_000_000, ["a", "b"],
                               {"customers": [], "total": 1_730_000.0})
        # 5,000,000 attributed against 5,000,000 remaining = 100%
        self.assertEqual(rec["revenue_excluding_attributed"], 5_000_000)
        self.assertEqual(rec["overstatement_pct"], 100)

    def test_no_revenue_leaves_shares_unset_rather_than_zero(self):
        rec = ledger.reconcile(self._reg(), None, None)
        self.assertIsNone(rec["equity_share_pct"])
        self.assertIsNone(rec["overstatement_pct"])
        self.assertEqual(rec["equity_total"], 3_270_000)   # register still works


class TestPricing(unittest.TestCase):
    def test_rate_card_is_read_from_the_filings(self):
        d = _corpus(a=RATE, b=RATE)
        cards = ledger.rate_card(d)
        self.assertEqual(cards[0]["low"], 5000.0)
        self.assertEqual(cards[0]["high"], 10000.0)

    def test_spread_against_the_published_price(self):
        d = _corpus(a=RATE + deal("Alpha LLC") + cash_deal("Vymedic, Inc."),
                    b=RATE + deal("Alpha LLC"))
        pr = ledger.pricing(ledger.engagement_register(d), ledger.rate_card(d))
        self.assertEqual(pr["published_high"], 10000.0)
        self.assertEqual(pr["equity_median"], 1_170_000.0)
        self.assertEqual(pr["multiple_vs_published"], 117)
        self.assertEqual(pr["multiple_vs_cash"], 29)   # 1.17M / 40k

    def test_no_rate_card_is_not_a_crash(self):
        d = _corpus(a=deal("Alpha LLC"), b=deal("Alpha LLC"))
        pr = ledger.pricing(ledger.engagement_register(d), ledger.rate_card(d))
        self.assertIsNone(pr["multiple_vs_published"])


class TestRepeatedFigures(unittest.TestCase):
    """Supporting anomaly check. Real, corroborative, not the headline."""

    def test_significant_digits(self):
        self.assertEqual(ledger.significant_digits("50,000"), 1)
        self.assertEqual(ledger.significant_digits("1,170,000"), 3)
        self.assertEqual(ledger.significant_digits("2,853,659"), 7)

    def test_finds_a_figure_shared_across_counterparties(self):
        body = deal("Alpha LLC") + deal("Bravo LLC") + deal("Charlie LLC")
        d = _corpus(a=body, b=body)
        rows = ledger.repeated_figures(d, min_parties=3)
        row = next(r for r in rows if r["amount"] == "2,853,659")
        self.assertEqual(row["parties"], ["Alpha LLC", "Bravo LLC", "Charlie LLC"])
        self.assertEqual(row["significance"], "STRONG")

    def test_round_figures_are_ranked_weak_but_never_discarded(self):
        """A repeated round number is ordinary commerce. It is also the CONTROL
        GROUP - what arm's-length customers paid - so dropping it silently was
        the first version's real mistake."""
        body = (deal("Alpha LLC", units="50,000", amount="50,000") +
                deal("Bravo LLC", units="50,000", amount="50,000") +
                deal("Charlie LLC", units="50,000", amount="50,000"))
        d = _corpus(a=body, b=body)
        rows = ledger.repeated_figures(d, min_parties=3)
        self.assertTrue(rows)
        self.assertTrue(all(r["significance"] == "WEAK" for r in rows))

    def test_multi_entity_paragraph_is_skipped(self):
        both = "Alpha LLC and Bravo LLC each received 9,999,999 units.\n\n"
        solo = deal("Charlie LLC", units="9,999,999")
        d = _corpus(a=both + solo, b=both + solo)
        rows = ledger.repeated_figures(d, min_parties=2)
        self.assertNotIn("9,999,999", {r["amount"] for r in rows})

    def test_alias_mention_blocks_association(self):
        """One sentence naming two companies by short form and none in full once
        fabricated an entire three-party cluster."""
        defs = ('a contract with ChipBrain LLC ("Chip") was signed.\n\n'
                'a contract with MustWatch LLC ("MW") was signed.\n\n'
                'a contract with Vymedic Inc. was signed.\n\n')
        d = _corpus(a=defs, b=defs)
        ents, aliases = ledger.discover_entities(d)
        hits = ledger._Matcher(ents, aliases).mentions(
            "netted with the gains of 204,600 and 1,661,868 in the MW and Chip "
            "securities held by Vymedic Inc.")
        # Only Vymedic is named in full. Without alias resolution this paragraph
        # looks single-entity and hands Chip's and MW's figures to Vymedic.
        self.assertEqual(hits, {"ChipBrain LLC", "MustWatch LLC", "Vymedic Inc."})

    def test_suffix_needs_a_trailing_boundary(self):
        """`Inc\\.?` once matched inside "Equity Incentive Plan"."""
        body = "Under the Equity Incentive Plan the Company issued 1,000,000 shares.\n\n"
        d = _corpus(a=body, b=body)
        ents, _ = ledger.discover_entities(d)
        self.assertEqual(ents, set())

    def test_name_does_not_absorb_the_preceding_word(self):
        body = "Technology\n\nMustWatch LLC received 1,000,000 units.\n\n"
        d = _corpus(a=body, b=body)
        ents, _ = ledger.discover_entities(d)
        self.assertIn("MustWatch LLC", ents)
        self.assertNotIn("Technology MustWatch LLC", ents)

    def test_near_miss_variant(self):
        body = (deal("Alpha LLC") + deal("Bravo LLC") + deal("Charlie LLC") +
                deal("Alpha LLC", units="2,856,659") +
                deal("Bravo LLC", units="2,856,659") +
                deal("Charlie LLC", units="2,856,659"))
        d = _corpus(a=body, b=body)
        nm = ledger.near_miss(ledger.repeated_figures(d, min_parties=3))
        hit = next(n for n in nm if n["a"] == "2,853,659")
        self.assertEqual(hit["delta"], 3000.0)
        self.assertEqual(len(hit["shared_parties"]), 3)


class TestAsEvidence(unittest.TestCase):
    def setUp(self):
        body = (RATE + deal("Alpha LLC") + deal("Bravo LLC") + deal("Charlie LLC")
                + cash_deal("Vymedic, Inc.")
                + conc("six-month period ended October 31, 2023", [("Zulu LLC", 25)]))
        self.d = _corpus(a=body, b=body)
        self.report = ledger.audit(
            self.d, reported_revenue=10_000_000,
            window=["2021-10-01", "2024-01-31"],
            quarters=[{"start": "2023-05-01", "end": "2023-07-31", "revenue": 1_000_000},
                      {"start": "2023-08-01", "end": "2023-10-31", "revenue": 3_000_000}])

    def test_headline_is_the_reconciliation(self):
        ev = ledger.as_evidence(self.report)
        self.assertEqual(ev[0]["method"], "revenue_reconciliation")
        self.assertIn("%", ev[0]["summary"])

    def test_pricing_comparator_is_present(self):
        methods = [e["method"] for e in ledger.as_evidence(self.report)]
        self.assertIn("pricing_comparator", methods)
        self.assertIn("disclosed_concentration", methods)

    def test_everything_is_inferred_and_sourced(self):
        ev = ledger.as_evidence(self.report)
        self.assertTrue(ev)
        self.assertTrue(all(e["tier"] == "INFERRED" for e in ev))
        self.assertTrue(all(e["source"] == "ledger" for e in ev))

    def test_no_reconciliation_without_revenue(self):
        rep = ledger.audit(self.d)
        methods = [e["method"] for e in ledger.as_evidence(rep)]
        self.assertNotIn("revenue_reconciliation", methods)
        self.assertIn("pricing_comparator", methods)   # still useful offline



class TestCitations(unittest.TestCase):
    """Every ledger fact must ship the sentence it came from.

    This is not a nicety. In a live run the ledger seeded the figure 2,853,659
    with no quote; the fleet spent its whole budget trying to re-derive the
    sentence from an eight-document sample, failed, and reported "these figures
    cannot be extracted from the filings" as a 0.95-confidence finding. The
    figures were in the filings. Seeding a claim without its evidence sends the
    fleet on an errand it cannot complete.
    """

    def test_quote_span_returns_the_whole_sentence(self):
        flat = ("Something earlier. In April 2023, the Company received 2,853,659 units "
                "of Alpha LLC as payment. And then something after.")
        i = flat.index("2,853,659")
        q = ledger.quote_span(flat, i, i + 9)
        self.assertTrue(q.startswith("In April 2023"))
        self.assertTrue(q.endswith("as payment."))
        self.assertNotIn("Something earlier", q)

    def test_quote_span_respects_the_cap(self):
        flat = "A " * 2000
        q = ledger.quote_span(flat, 100, 110, max_chars=200)
        self.assertLessEqual(len(q), 200)

    def test_register_rows_carry_a_citation(self):
        d = _corpus(a=deal("Alpha LLC"), b=deal("Alpha LLC"))
        row = ledger.engagement_register(d)["equity"][0]
        self.assertIn("file", row["citation"])
        self.assertIn("2,853,659", row["citation"]["quote"])

    def test_every_emitted_citation_is_verbatim(self):
        """The quote must appear in the file it names, under the same whitespace
        normalisation CitationGuard uses - otherwise the guard quarantines the
        deterministic screen's own output."""
        body = (RATE + deal("Alpha LLC") + deal("Bravo LLC") + deal("Charlie LLC")
                + cash_deal("Vymedic, Inc.")
                + conc("six-month period ended October 31, 2023", [("Zulu LLC", 25)]))
        d = _corpus(a=body, b=body)
        rep = ledger.audit(d, 10_000_000, ["a", "b"], quarters=[
            {"start": "2023-05-01", "end": "2023-07-31", "revenue": 1_000_000},
            {"start": "2023-08-01", "end": "2023-10-31", "revenue": 3_000_000}])
        norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
        docs = {f: norm(open(os.path.join(d, f)).read())
                for f in os.listdir(d) if f.endswith(".txt")}
        n = 0
        for e in ledger.as_evidence(rep):
            for c in e.get("citations", []):
                n += 1
                self.assertIn(c["file"], docs, e["id"])
                self.assertIn(norm(c["quote"]), docs[c["file"]],
                              f"{e['id']}: {c['quote'][:60]}")
        self.assertGreater(n, 4)

    def test_headline_evidence_is_never_uncited(self):
        body = RATE + deal("Alpha LLC") + deal("Bravo LLC")
        d = _corpus(a=body, b=body)
        rep = ledger.audit(d, 10_000_000, ["a", "b"])
        for e in ledger.as_evidence(rep):
            self.assertTrue(e.get("citations"), f"{e['id']} shipped with no citation")


@unittest.skipUnless(os.path.isdir("corpus"), "corpus not present")
class TestAgainstRealCorpus(unittest.TestCase):
    """Regression against the 71 real EDGAR filings.

    Revenue is hard-coded rather than fetched so the suite stays offline; the
    value is forensic.revenue_timeline's output for the SEC's Relevant Period,
    asserted independently in test_forensic.
    """
    REVENUE = 16_754_071.0
    QUARTERS = [
        {"start": "2021-11-01", "end": "2022-01-31", "revenue": 1811041},
        {"start": "2022-02-01", "end": "2022-04-30", "revenue": 1844785},
        {"start": "2022-05-01", "end": "2022-07-31", "revenue": 1340573},
        {"start": "2022-08-01", "end": "2022-10-31", "revenue": 1778973},
        {"start": "2022-11-01", "end": "2023-01-31", "revenue": 2260414},
        {"start": "2023-02-01", "end": "2023-04-30", "revenue": 3114025},
        {"start": "2023-05-01", "end": "2023-07-31", "revenue": 1519809},
        {"start": "2023-08-01", "end": "2023-10-31", "revenue": 2041658},
        {"start": "2023-11-01", "end": "2024-01-31", "revenue": 1042793},
    ]

    @classmethod
    def setUpClass(cls):
        cls.report = ledger.audit("corpus", cls.REVENUE,
                                  ["2021-10-01", "2024-01-31"], quarters=cls.QUARTERS)

    def test_recovers_every_charged_portfolio_company(self):
        """The eleven companies the SEC charged. Neither extraction route finds
        all of them alone: eight come from the Investments note, three only from
        the concentration tables."""
        charged = {"AceHedge LLC", "CountSharp LLC", "CupCrew LLC", "Cust Corp",
                   "Dark LLC", "Fantize LLC", "HeadFarm LLC", "NetWire LLC",
                   "RealWorld LLC", "Reper LLC", "StockText LLC"}
        found = set(self.report["counterparties"])
        self.assertTrue(charged <= found, f"missed: {sorted(charged - found)}")

    def test_both_routes_are_load_bearing(self):
        reg = {r["counterparty"] for r in self.report["register"]["equity"]}
        self.assertNotIn("AceHedge LLC", reg)          # concentration only
        self.assertIn("CountSharp LLC", reg)           # register only
        conc_names = {c["counterparty"] for p in self.report["concentration"]
                      for c in p["customers"]}
        self.assertIn("AceHedge LLC", conc_names)
        self.assertNotIn("CountSharp LLC", conc_names)

    def test_cash_comparators_are_not_in_the_equity_bucket(self):
        """C-Reveal and Vymedic paid cash. Misfiling them as equity would inflate
        the reconciliation and destroy the pricing comparison."""
        eq = {r["counterparty"] for r in self.report["register"]["equity"]}
        cash = {r["counterparty"] for r in self.report["register"]["cash"]}
        self.assertIn("Vymedic, Inc", cash)
        self.assertIn("C-Reveal Therapeutics LLC", cash)
        self.assertFalse(eq & cash)

    def test_reconciliation_lands_near_the_withheld_complaint(self):
        """The SEC alleges $13,969,013 of improper revenue, ~77% of the period's
        total. This module never sees the complaint. It reports $14.58M / 87%,
        the difference being two equity-settled counterparties (ScanHash,
        Hiveskill) the SEC chose not to charge.
        """
        rec = self.report["reconciliation"]
        self.assertEqual(rec["equity_counterparties"], 10)
        self.assertAlmostEqual(rec["equity_total"], 11_905_000, delta=1)
        self.assertAlmostEqual(rec["derived_total"], 2_671_099, delta=2)
        self.assertGreater(rec["attributed_share_pct"], 80)
        # Excluding the two uncharged counterparties, within 6% of the SEC figure.
        adjusted = rec["attributed_total"] - 1_425_000
        self.assertLess(abs(adjusted - 13_969_013) / 13_969_013, 0.06)

    def test_pricing_spread_against_the_published_rate_card(self):
        pr = self.report["pricing"]
        self.assertEqual(pr["published_low"], 5_000)
        self.assertEqual(pr["published_high"], 10_000)
        self.assertEqual(pr["cash_low"], 40_000)
        self.assertGreater(pr["multiple_vs_published"], 100)

    def test_the_fingerprint_still_holds(self):
        strong = {r["amount"] for r in self.report["repeated_figures"]
                  if r["significance"] == "STRONG"}
        self.assertEqual(strong, {"2,853,659", "2,856,659", "1,170,000"})

    def test_the_known_distractor_cluster_stays_dead(self):
        for r in self.report["repeated_figures"]:
            self.assertNotEqual(r["amount"], "1,661,868")
            self.assertNotIn("ChipBrain LLC", r["parties"])

    def test_seed_evidence_leads_with_the_reconciliation(self):
        ev = ledger.as_evidence(self.report)
        self.assertEqual(ev[0]["method"], "revenue_reconciliation")
        self.assertGreaterEqual(len(ev), 6)
        self.assertTrue(all(e["tier"] == "INFERRED" for e in ev))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad}/{result.testsRun} passed")
    sys.exit(1 if bad else 0)
