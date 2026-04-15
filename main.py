from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from src.catalog import (
    build_markdown_report,
    build_topic_summary,
    extract_authorship_rows,
    write_csv,
    write_json,
    write_sqlite,
)
from src.fetchers import APIError, resolve_metadata, search_arxiv, search_openalex, search_semanticscholar, set_email


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scarica articoli da arXiv, arricchisce con OpenAlex e cataloga per topic, autore e universita."
        )
    )
    parser.add_argument(
        "--topics",
        nargs="+",
        default=["numerical relativity"],
        help="Uno o piu argomenti (default: numerical relativity).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=30,
        help="Numero massimo di articoli arXiv per topic (default: 30).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Pausa in secondi tra chiamate API (default: 0.25).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data"),
        help="Directory di output per CSV/JSON (default: data).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports"),
        help="Directory dei report markdown (default: reports).",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Email per OpenAlex polite pool (aumenta rate limit).",
    )
    parser.add_argument(
        "--filter-keywords",
        nargs="+",
        default=None,
        metavar="KW",
        help="Filtra articoli: tieni solo quelli che contengono queste keyword nell'abstract.",
    )
    parser.add_argument(
        "--filter-mode",
        choices=["any", "all"],
        default="any",
        help="'any': basta una keyword nell'abstract. 'all': devono esserci tutte (default: any).",
    )
    parser.add_argument(
        "--countries",
        nargs="+",
        default=["CH"],
        metavar="CC",
        help="Codici paese ISO da evidenziare (default: CH). Es: CH DE NL FR.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        metavar="FILE",
        help="Percorso database SQLite di output (es: data/thesis.db). Se omesso, non viene generato.",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=["arxiv", "openalex", "semanticscholar"],
        default=["arxiv"],
        help="Fonti da cui scaricare articoli (default: arxiv). Es: arxiv openalex semanticscholar.",
    )
    parser.add_argument(
        "--journals",
        nargs="+",
        default=["all"],
        metavar="J",
        help=(
            "Filtra per rivista (substring, case-insensitive). "
            "'all' = nessun filtro (default). "
            "Es: --journals 'Physical Review' 'Astrophysical' JCAP"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.email:
        set_email(args.email)
    else:
        print("Avviso: --email non impostata. OpenAlex usa rate limit ridotto.", file=sys.stderr)
    target_countries = {c.upper() for c in args.countries}
    print(f"Paesi selezionati: {', '.join(sorted(target_countries))}")
    all_articles: list[dict] = []
    all_rows: list[dict] = []

    for topic in args.topics:
        print(f"\n[1/3] Ricerca articoli per topic: {topic}")
        raw_articles: list[dict] = []

        if "arxiv" in args.sources:
            try:
                found = search_arxiv(topic=topic, max_results=args.max_results, sleep_s=args.sleep)
                print(f"  arXiv: {len(found)} articoli")
                raw_articles.extend(found)
            except APIError as exc:
                print(f"  Errore arXiv: {exc}", file=sys.stderr)

        if "openalex" in args.sources:
            try:
                found = search_openalex(topic=topic, max_results=args.max_results)
                print(f"  OpenAlex: {len(found)} articoli")
                raw_articles.extend(found)
            except APIError as exc:
                print(f"  Errore OpenAlex: {exc}", file=sys.stderr)

        if "semanticscholar" in args.sources:
            try:
                found = search_semanticscholar(topic=topic, max_results=args.max_results)
                print(f"  Semantic Scholar: {len(found)} articoli")
                raw_articles.extend(found)
            except APIError as exc:
                print(f"  Errore Semantic Scholar: {exc}", file=sys.stderr)

        # Deduplica per DOI, poi per titolo normalizzato
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()
        articles: list[dict] = []
        for a in raw_articles:
            doi = (a.get("doi") or "").strip().lower()
            title_key = " ".join((a.get("title") or "").lower().split())
            if doi and doi in seen_dois:
                continue
            if title_key and title_key in seen_titles:
                continue
            if doi:
                seen_dois.add(doi)
            if title_key:
                seen_titles.add(title_key)
            articles.append(a)

        print(f"  - Totale dopo deduplica: {len(articles)} articoli")

        if args.journals != ["all"]:
            journals_lower = [j.lower() for j in args.journals]
            articles = [
                a for a in articles
                if any(j in (a.get("journal") or "").lower() for j in journals_lower)
            ]
            print(f"  - Dopo filtro riviste {args.journals}: {len(articles)} articoli")

        if args.filter_keywords:
            check = all if args.filter_mode == "all" else any
            keywords_lower = [kw.lower() for kw in args.filter_keywords]
            articles = [
                a for a in articles
                if check(kw in (a.get("summary") or "").lower() for kw in keywords_lower)
            ]
            print(f"  - Dopo filtro abstract ({args.filter_mode} {args.filter_keywords}): {len(articles)} articoli")

        for idx, article in enumerate(articles, start=1):
            print(f"[2/3] ({topic}) arricchimento OpenAlex {idx}/{len(articles)}", end="\r", flush=True)
            try:
                work = resolve_metadata(article, title_fallback=True)
            except APIError:
                work = None

            if work is None:
                print(f"  Avviso: nessun match OpenAlex per '{article.get('title', '')[:60]}'", file=sys.stderr)

            article_record = {
                "topic": topic,
                "article": article,
                "openalex": work,
            }
            all_articles.append(article_record)
            all_rows.extend(extract_authorship_rows(topic, article, work, target_countries))
            time.sleep(args.sleep)

        print()
        report_text = build_markdown_report(topic, all_rows)
        report_path = args.report_dir / f"report_{topic.replace(' ', '_').lower()}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"[3/3] Report topic salvato in: {report_path}")

    if not all_articles:
        print("Nessun dato salvato.")
        return 1

    raw_json = args.out_dir / "articles_enriched.json"
    write_json(raw_json, all_articles)

    rows_csv = args.out_dir / "catalog.csv"
    write_csv(
        rows_csv,
        all_rows,
        headers=["topic", "source", "arxiv_id", "title", "doi", "published", "journal", "author", "university", "country", "is_target"],
    )

    summary_rows = build_topic_summary(all_rows)
    summary_csv = args.out_dir / "topic_summary.csv"
    write_csv(
        summary_csv,
        summary_rows,
        headers=[
            "topic",
            "total_articles",
            "articles_with_target_authors",
            "target_authorship_rows",
            "target_ratio",
        ],
    )

    if args.db:
        write_sqlite(args.db, all_rows)

    print("\nOutput generati:")
    print(f"- {raw_json}")
    print(f"- {rows_csv}")
    print(f"- {summary_csv}")
    if args.db:
        print(f"- {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
