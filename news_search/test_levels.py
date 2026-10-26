"""News level and the effect of dropping one profile field. No corpus and no model."""
from news_search.levels import diversity, jaccard, news_level, overlap_at_k, rank_corr, top_ids, zone_of


def test_irkutsk_is_siberia_and_a_federal_story_is_not_a_region():
    assert zone_of("Иркутская область") == "siberia_fe"
    assert zone_of("Москва") == "moscow" and zone_of("Московская область") == "moscow"
    assert news_level(["siberia_fe"], "siberia_fe") == "same_region"
    assert news_level(["moscow"], "siberia_fe") == "other_region"
    assert news_level(["russia_all"], "siberia_fe") == "federal"
    assert news_level(["foreign"], "moscow") == "international"
    assert news_level(["moscow", "russia_all"], "moscow") == "same_region"


def test_dropping_the_region_changes_the_headline_list_and_revenue_does_not():
    news = [
        {"sid": "A1", "event": "В Иркутске сократилось число компаний"},
        {"sid": "A2", "event": "Строительство жилья в России сократилось"},
        {"sid": "A3", "event": "Матч завершился вничью"},
    ]
    full = "строительство Иркутск выручка 62 млрд"
    no_region = "строительство выручка 62 млрд"
    no_revenue = "строительство Иркутск"
    assert top_ids(full, news, 2)[0] == "A1"
    assert jaccard(top_ids(full, news, 2), top_ids(no_region, news, 2)) < 1
    assert top_ids(full, news, 3) == top_ids(no_revenue, news, 3)
    assert overlap_at_k(["A1", "A2"], ["A1", "A2"], 2) == 1
    assert overlap_at_k(["A1", "A2"], ["A2", "A3"], 2) == 0.5
    assert rank_corr(["A1", "A2"], ["A1", "A2"], 2) == 1
    assert rank_corr(["A1", "A2"], ["A2", "A1"], 2) < 0
    assert rank_corr(["A1", "A2"], ["A9", "A8"], 2) == 0
    assert diversity([{"region": ["russia_all"]}, {"region": ["foreign"]}], "moscow") == 0.5
