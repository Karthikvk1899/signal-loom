import pytest
from pydantic import ValidationError

from loom.domain import Bundle, Flag, bucket, evaluate


def bundle(**kwargs):
    return Bundle(flags=[Flag(key="checkout", rollout=5000, salt="v1", **kwargs)])


@pytest.mark.parametrize("percent,expected", [(0, False), (10000, True)])
def test_boundaries(percent, expected):
    b = Bundle(flags=[Flag(key="checkout", rollout=percent, salt="v1")])
    assert all(evaluate(b, "acme/prod", "checkout", str(n))["value"] == expected for n in range(1000))


def test_precedence_and_missing():
    assert evaluate(bundle(allow=["x"], deny=["x"]), "e", "checkout", "x")["reason"] == "deny"
    assert evaluate(bundle(allow=["x"]), "e", "checkout", "x")["value"]
    assert not evaluate(bundle(enabled=False, allow=["x"]), "e", "checkout", "x")["value"]
    assert evaluate(bundle(), "e", "absent", "x")["reason"] == "missing"


def test_cohorts_are_stable_and_monotonic():
    b = bundle()
    values = [bucket("acme/prod", b.flags[0], str(i)) for i in range(2000)]
    assert values == [bucket("acme/prod", b.flags[0], str(i)) for i in range(2000)]
    low = {i for i, value in enumerate(values) if value < 1000}
    high = {i for i, value in enumerate(values) if value < 4000}
    assert low < high
    assert values != [bucket("other/prod", b.flags[0], str(i)) for i in range(2000)]


@pytest.mark.parametrize(
    "change",
    [
        {"rollout": -1},
        {"rollout": 10001},
        {"rollout": True},
        {"rollout": "50"},
        {"enabled": "false"},
        {"key": "bad key"},
        {"salt": ""},
        {"unknown": 1},
    ],
)
def test_invalid_flag(change):
    with pytest.raises(ValidationError):
        Flag.model_validate({"key": "checkout", "rollout": 50, "salt": "v1", **change})


def test_duplicate_and_future_schema_rejected():
    flag = bundle().flags[0]
    with pytest.raises(ValidationError):
        Bundle(flags=[flag, flag])
    with pytest.raises(ValidationError):
        Bundle(schema_version=2, flags=[])
