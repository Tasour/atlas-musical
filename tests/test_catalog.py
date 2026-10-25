from analysis.catalog import PUBLIC_TRACKS, TRACKS

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


def test_public_catalog_is_well_formed():
    assert len(PUBLIC_TRACKS) == 20
    assert len({track["id"] for track in PUBLIC_TRACKS}) == len(PUBLIC_TRACKS)
    assert len({track["youtube_id"] for track in PUBLIC_TRACKS}) == len(PUBLIC_TRACKS)

    for track in PUBLIC_TRACKS:
        assert REQUIRED_FIELDS <= track.keys()
        assert track["source_url"].startswith("https://www.youtube.com/watch?v=")
        assert track["license_url"].startswith("https://creativecommons.org/")
        assert track["family"] in {"acoustique", "cinematique", "tropical", "intense"}


def test_merged_catalog_has_unique_tracks():
    assert len(TRACKS) >= len(PUBLIC_TRACKS)
    assert len({track["id"] for track in TRACKS}) == len(TRACKS)
    assert len({track["youtube_id"] for track in TRACKS}) == len(TRACKS)
