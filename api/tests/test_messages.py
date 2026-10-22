from pathlib import Path

import pytest
import yaml

from app.assistant.messages import MESSAGES

SPEC = yaml.safe_load((Path(__file__).parent / "fixtures" / "srs_messages.yaml").read_text())


@pytest.mark.parametrize("message_id", sorted(SPEC))
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_1_7_2_a_message_matches_spec(message_id: str, lang: str) -> None:
    assert MESSAGES[message_id][lang] == SPEC[message_id][lang]  # type: ignore[index]


def test_2_9_1_every_message_defined_in_both_languages() -> None:
    assert set(MESSAGES) == set(SPEC)
    for texts in MESSAGES.values():
        assert set(texts) == {"en", "ar"}
        assert all(t.strip() for t in texts.values())
