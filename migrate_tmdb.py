"""Run the legacy TVDB-to-TMDB library migration explicitly."""

from dotenv import load_dotenv

load_dotenv()

from lib import db, tmdb


def main():
    if not tmdb.is_configured():
        raise SystemExit(
            "Set TMDB_API_TOKEN (recommended) or TMDB_API_KEY before migrating."
        )

    db.init_db()
    report = db.migrate_legacy_content(tmdb)
    print(
        f"Checked {report['checked']} rows; migrated {report['migrated']}; "
        f"unmatched {len(report['unmatched'])}; errors {len(report['errors'])}."
    )
    for title in report["unmatched"]:
        print(f"Unmatched: {title}")
    for error in report["errors"]:
        print(f"Error: {error}")

    if report["unmatched"] or report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
