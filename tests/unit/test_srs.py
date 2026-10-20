import pytest

from societytwin.sampling.srs import ALGORITHM_VERSION, SamplingError, design_weights, simple_random_sample

FRAME = [f"ID_{i:03d}" for i in range(1, 51)]


def test_same_frame_seed_and_version_give_same_ids_regardless_of_input_order():
    a = simple_random_sample(FRAME, 10, 42)
    b = simple_random_sample(list(reversed(FRAME)), 10, 42)
    assert a == b
    assert len(set(a)) == 10 and set(a) <= set(FRAME)


def test_golden_sample_pins_the_algorithm():
    # If this changes, bump ALGORITHM_VERSION: stored cohort manifests depend on it.
    assert ALGORITHM_VERSION == "srs-sha256-fisher-yates-v1"
    assert simple_random_sample(["a", "b", "c", "d", "e"], 3, 0) == ['a', 'b', 'e']
    assert simple_random_sample(FRAME, 5, 1) == ['ID_005', 'ID_036', 'ID_024', 'ID_018', 'ID_031']
    assert simple_random_sample(FRAME, 5, 1) != simple_random_sample(FRAME, 5, 2)


def test_full_frame_is_a_permutation():
    assert sorted(simple_random_sample(FRAME, 50, 9)) == FRAME


@pytest.mark.parametrize("size, seed, code", [(51, 1, "oversample"), (0, 1, "invalid_size"), (5, -1, "invalid_seed"),
                                              (5, 2**63, "invalid_seed")])
def test_invalid_requests(size, seed, code):
    with pytest.raises(SamplingError) as info:
        simple_random_sample(FRAME, size, seed)
    assert info.value.code == code


def test_duplicate_frame_rejected():
    with pytest.raises(SamplingError):
        simple_random_sample(["a", "a", "b"], 1, 1)


def test_weights_are_relative_to_eligible_synthetic_frame():
    w = design_weights(40, 10)
    assert w["inclusion_probability"] == 0.25 and w["synthetic_frame_expansion_weight"] == 4.0
    assert "synthetic build only" in w["weight_scope"]
