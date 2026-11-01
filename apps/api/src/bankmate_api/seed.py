import argparse

from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import get_session_factory
from bankmate_api.seed_data import DATASET_VERSION, seed_demo_data
from bankmate_api.showcase_seed import seed_submission_showcase


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic BankMate data.")
    parser.add_argument(
        "--showcase",
        action="store_true",
        help="Also seed deterministic records for every product page.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise SystemExit("Synthetic seed is allowed only in development or test environments.")
    session_factory = get_session_factory(settings.database_url)
    if args.showcase:
        page_counts = seed_submission_showcase(session_factory)
        print("Seeded BankMate submission showcase data (all records are synthetic):")
        for page, count in page_counts.items():
            print(f"  {page}: {count}")
    else:
        with session_factory.begin() as session:
            seed_demo_data(session)
        print(f"Seeded synthetic dataset {DATASET_VERSION}.")


if __name__ == "__main__":
    main()
