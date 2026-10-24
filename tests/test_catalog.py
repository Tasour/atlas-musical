from analysis.catalog import TRACKS

REQUIRED_FIELDS = {
    "id",
    "youtube_id",
    "title",
    "artist",
    "credit",
    "license",
    "license_url",
    "source_url",
    "family",
}


def test_catalog_is_well_formed():
    assert len(TRACKS) == 20
    assert len({track["id"] for track in TRACKS}) == len(TRACKS)
    assert len({track["youtube_id"] for track in TRACKS}) == len(TRACKS)

    for track in TRACKS:
        assert REQUIRED_FIELDS <= track.keys()
        assert track["source_url"].startswith("https://www.youtube.com/watch?v=")
        assert track["license_url"].startswith("https://creativecommons.org/")
        assert track["family"] in {"acoustique", "cinematique", "tropical", "intense"}
