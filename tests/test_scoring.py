from biibaa.scoring import (
    DOWNLOADS_REF_NPM,
    effort_score,
    final_score,
    impact,
    popularity,
    severity_score,
)


def test_popularity_zero_for_unknown_package():
    assert popularity(downloads_weekly=0, stars=0) == 0.0


def test_popularity_clipped_at_100_for_reference_package():
    # At reference traffic, normalized download component = 1.0 → 70.
    # Stars unknown contributes 0. Score should be ~70.
    pop = popularity(downloads_weekly=DOWNLOADS_REF_NPM, stars=None)
    assert 65 < pop <= 100


def test_popularity_monotonic_in_downloads():
    a = popularity(downloads_weekly=1_000, stars=None)
    b = popularity(downloads_weekly=10_000_000, stars=None)
    assert b > a


def test_severity_score_maps_cvss_linearly():
    assert severity_score(cvss=10.0) == 100.0
    assert severity_score(cvss=5.0) == 50.0
    assert severity_score(cvss=None) == 50.0  # unknown → moderate


def test_effort_score_drop_in_for_minor_bump():
    assert effort_score(fixed_versions=["4.7.9"], advisory_summary="patch fix") == 95.0


def test_effort_score_penalises_breaking_summary():
    assert (
        effort_score(fixed_versions=["5.0.0"], advisory_summary="breaking rewrite required")
        == 60.0
    )


def test_final_score_is_weighted_blend():
    # 0.7 * 80 + 0.3 * 50 = 56 + 15 = 71
    assert final_score(impact_value=80, effort_value=50) == 71.0


def test_impact_combines_popularity_and_severity():
    # pop=50 → 0.5 ; sev=80 → 80 ; impact = 40
    assert impact(pop=50.0, sev=80.0) == 40.0
