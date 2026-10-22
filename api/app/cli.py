"""python -m app.cli seed   -> recreate the schema, load users and ingest the corpus."""

import sys
import time

from app.config import settings
from app.db.session import as_owner, migrate
from app.ingest.index import ingest_corpus, seed_people


def seed() -> None:
    started = time.perf_counter()
    with as_owner() as conn:
        migrate(conn)
        seed_people(conn)
        counts = ingest_corpus(conn)
    provider = "cohere" if settings.use_live_cohere() else "offline hasher"
    print(  # noqa: T201
        f"seeded {len(counts)} documents, {sum(counts.values())} passages "
        f"({provider} embeddings) in {time.perf_counter() - started:.1f}s"
    )


if __name__ == "__main__":
    commands = {"seed": seed}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python -m app.cli {{{'|'.join(commands)}}}")
    commands[sys.argv[1]]()
