from vendorcheck import bench


def test_every_bench_scenario_is_green():
    results = bench.run_all()
    bad = [(r["id"], [p for row in r["rows"] for p in row["problems"]]) for r in results if not r["ok"]]
    assert not bad, bad
    assert len(results) >= 15


def test_mutations_are_caught_offline_without_api_calls():
    for kind, rule in [("flip_gstin", "R06"), ("swap_pan", "R08"), ("change_state", "R06")]:
        r = bench.run_mutation("zoho", kind)
        assert r["gst_calls"] == 0 and any(f[0] == rule for f in r["flagged"]), (kind, r)
