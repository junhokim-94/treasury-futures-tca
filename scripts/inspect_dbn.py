"""Print a small sample of records from a local Databento DBN file."""

import argparse
from itertools import islice


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to a DBN or compressed DBN file")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")

    import databento as db

    for record in islice(db.DBNStore.from_file(args.path), args.limit):
        print(record)


if __name__ == "__main__":
    main()

