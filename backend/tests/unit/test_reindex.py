from collections.abc import Sequence

import pytest

from app.llm.base import ProviderUnavailableError
from app.reindex import main


class _Embedder:
    """Records each request and fails it, so that a run past the check stops at the probe."""

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return "text-embedding-3-small"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        raise ProviderUnavailableError("The AI provider could not be reached.")


@pytest.mark.parametrize("args", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_outside_the_worker_container_the_command_stops_before_the_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    # As in a host shell: Compose sets the variable in the worker container.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    embedder = _Embedder()

    assert main(args, embedder=embedder) == 1

    assert embedder.requests == []
    output = capsys.readouterr().out
    assert "docker compose exec worker python -m app.reindex" in output
    assert output.splitlines()[-1].endswith("Nothing was changed.")


def test_help_is_shown_outside_the_worker_container_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as caught:
        main(["--help"])

    assert caught.value.code == 0
    assert "--dry-run" in capsys.readouterr().out
