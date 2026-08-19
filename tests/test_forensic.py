"""Offline tests for the deterministic forensic screens. No network, no API key."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casezero.forensic import m_score, accrual_screen, as_evidence

CLEAN = dict(revenue=10_000_000, cogs=6_000_000, receivables=1_000_000, assets=8_000_000,
             current_assets=4_000_000, ppe=2_000_000, securities=0, cfo=1_200_000,
             net_income=1_000_000, current_liabilities=2_000_000, liabilities=2_500_000,
             ltd=500_000, sga=2_000_000, depreciation=200_000)

PRIOR = dict(CLEAN, revenue=9_500_000, receivables=950_000, net_income=900_000, cfo=1_100_000)


def test_healthy_company_scores_below_threshold():
    r = m_score(CLEAN, PRIOR)
    assert r["m_score"] < -1.78, r["m_score"]
    assert r["flagged"] is False
    print(f"PASS  a cash-generating company scores {r['m_score']:.2f}, below threshold")


def test_accrual_divergence_drives_the_score_up():
    """Profit with negative operating cash flow is the signal that matters."""
    bad = dict(CLEAN, net_income=3_000_000, cfo=-3_000_000)
    r = m_score(bad, PRIOR)
    assert r["flagged"] is True
    assert r["dominant_driver"] == "TATA", r["dominant_driver"]
    assert r["contributions"]["TATA"] > 0
    print(f"PASS  profit-without-cash flags at {r['m_score']:.2f}, driven by TATA")


def test_accrual_screen_detects_and_quantifies():
    a = accrual_screen(dict(net_income=2_954_972, cfo=-4_617_200, revenue=8_493_985))
    assert a["profit_without_cash"] is True
    assert a["gap"] == 7_572_172
    assert 0.89 < a["gap_over_revenue"] < 0.90
    b = accrual_screen(dict(net_income=1_000_000, cfo=1_200_000, revenue=10_000_000))
    assert b["profit_without_cash"] is False
    print(f"PASS  accrual screen: gap ${a['gap']:,} = {a['gap_over_revenue']:.0%} of revenue")


def test_missing_inputs_are_reported_not_guessed():
    sparse = dict(CLEAN, receivables=None, depreciation=None)
    r = m_score(sparse, dict(PRIOR, receivables=None, depreciation=None))
    assert "DSRI" in r["unavailable"] and "DEPI" in r["unavailable"]
    assert r["indices"]["DSRI"] == 1.0, "unavailable index must sit at neutral"
    print(f"PASS  unavailable indices reported ({', '.join(r['unavailable'])}), held at neutral")


def test_evidence_is_inferred_never_direct():
    """A derived statistical screen must never enter the graph as DIRECT."""
    res = {"years": [dict(m_score(dict(CLEAN, net_income=3_000_000, cfo=-3_000_000), PRIOR),
                          fiscal_year_end="2023-04-30", revenue=8_493_985,
                          net_income=3_000_000, cfo=-3_000_000,
                          accruals=accrual_screen(dict(net_income=3_000_000, cfo=-3_000_000,
                                                       revenue=8_493_985)))]}
    ev = as_evidence(res)
    assert ev and all(e["tier"] == "INFERRED" for e in ev), [e["tier"] for e in ev]
    assert any(e["method"] == "accruals_divergence" for e in ev)
    assert any(e["method"] == "beneish_m_score" for e in ev)
    assert all("not a finding of fraud" in e["summary"] or "did not arrive as cash" in e["summary"]
               for e in ev)
    print(f"PASS  {len(ev)} seed objects, all INFERRED, both methods represented")


def test_no_flag_when_cash_backs_the_profit():
    ev = as_evidence({"years": [dict(m_score(CLEAN, PRIOR), fiscal_year_end="2023-04-30",
                                     revenue=10_000_000, net_income=1_000_000, cfo=1_200_000,
                                     accruals=accrual_screen(CLEAN))]})
    assert ev == [], ev
    print("PASS  a healthy year emits no seed evidence at all")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\n{len(fns)}/{len(fns)} passed")
