"""Filename pairing across all five buckets (PRD §5.5, acceptance test 14)."""

import batching

HEADER = "filename,brand_name,class_type,alcohol_content,net_contents,applicant"


def _rows(*filenames: str) -> list[dict[str, str]]:
    csv = "\n".join([HEADER, *(f"{f},Brand,Class,45%,750 mL,Applicant" for f in filenames)])
    return batching.parse_csv(csv.encode())


def test_stem_normalises_case_separators_and_extension() -> None:
    assert batching.stem("Old_Tom_750.JPG") == batching.stem("old-tom-750.jpg")
    assert batching.stem("./sub/dir/A B.png") == "a-b"


def test_missing_required_columns_is_a_field_level_error() -> None:
    try:
        batching.parse_csv(b"filename,brand_name\n")
    except batching.BatchCsvError as exc:
        assert "class_type" in str(exc)
    else:
        raise AssertionError("expected BatchCsvError")


def test_exact_match() -> None:
    rows, unused = batching.pair(_rows("old-tom.png"), ["old-tom.png"])
    assert rows[0].bucket == "matched"
    assert rows[0].image == "old-tom.png"
    assert unused == []


def test_normalised_match_pairs_across_case_and_separators() -> None:
    rows, _ = batching.pair(_rows("Old_Tom_750.jpg"), ["old-tom-750.jpg"])
    assert rows[0].bucket == "matched"


def test_extension_agnostic_match_is_flagged_fuzzy() -> None:
    rows, _ = batching.pair(_rows("old-tom.png"), ["old-tom.jpg"])
    assert rows[0].bucket == "matched_fuzzy"
    assert rows[0].image == "old-tom.jpg"


def test_missing_image_files_but_does_not_block() -> None:
    rows, _ = batching.pair(_rows("old-tom.png"), [])
    assert rows[0].bucket == "missing_image"
    assert not batching.blocks_commit(rows)


def test_ambiguous_pair_errors_and_blocks_commit() -> None:
    rows, _ = batching.pair(_rows("old-tom.png"), ["Old_Tom.jpg", "old-tom.jpeg"])
    assert rows[0].bucket == "ambiguous"
    assert rows[0].candidate_filenames == ["Old_Tom.jpg", "old-tom.jpeg"]
    assert batching.blocks_commit(rows)


def test_unused_images_are_listed_so_nothing_vanishes() -> None:
    rows, unused = batching.pair(_rows("old-tom.png"), ["old-tom.png", "stray.jpg"])
    assert rows[0].bucket == "matched"
    assert unused == ["stray.jpg"]
