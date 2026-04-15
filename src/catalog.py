from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def extract_authorship_rows(
    topic: str,
    article: dict[str, Any],
    openalex_work: dict[str, Any] | None,
    target_countries: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not openalex_work:
        return rows

    work_title = openalex_work.get("display_name") or article.get("title") or ""
    work_doi = (openalex_work.get("doi") or "").replace("https://doi.org/", "") or article.get("doi") or ""

    for authorship in openalex_work.get("authorships", []) or []:
        author_name = (authorship.get("author") or {}).get("display_name", "")
        institutions = authorship.get("institutions") or []

        if not institutions:
            rows.append(
                {
                    "topic": topic,
                    "source": article.get("source", ""),
                    "arxiv_id": article.get("arxiv_id", ""),
                    "title": work_title,
                    "doi": work_doi,
                    "published": article.get("published", ""),
                    "author": author_name,
                    "university": "",
                    "country": "",
                    "is_target": False,
                }
            )
            continue

        for inst in institutions:
            country = inst.get("country_code", "")
            rows.append(
                {
                    "topic": topic,
                    "source": article.get("source", ""),
                    "arxiv_id": article.get("arxiv_id", ""),
                    "title": work_title,
                    "doi": work_doi,
                    "published": article.get("published", ""),
                    "author": author_name,
                    "university": inst.get("display_name", ""),
                    "country": country,
                    "is_target": country in target_countries,
                }
            )

    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_topic_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_topic[row["topic"]].append(row)

    summary: list[dict[str, Any]] = []
    for topic, topic_rows in by_topic.items():
        article_ids = {r["arxiv_id"] for r in topic_rows if r["arxiv_id"]}
        target_rows = [r for r in topic_rows if r["is_target"]]
        target_article_ids = {r["arxiv_id"] for r in target_rows if r["arxiv_id"]}

        total_articles = len(article_ids)
        target_articles = len(target_article_ids)
        target_ratio = (target_articles / total_articles) if total_articles else 0.0

        summary.append(
            {
                "topic": topic,
                "total_articles": total_articles,
                "articles_with_target_authors": target_articles,
                "target_authorship_rows": len(target_rows),
                "target_ratio": round(target_ratio, 3),
            }
        )

    summary.sort(key=lambda x: x["target_ratio"], reverse=True)
    return summary


def build_markdown_report(topic: str, rows: list[dict[str, Any]], max_authors: int = 20) -> str:
    target_rows = [r for r in rows if r["is_target"] and r["topic"] == topic]
    if not target_rows:
        return (
            f"# Report Topic: {topic}\n\n"
            "Nessuna affiliazione nei paesi selezionati trovata nel campione. "
            "Aumenta `--max-results` o prova keyword vicine.\n"
        )

    by_author = Counter((r["author"], r["university"], r["country"]) for r in target_rows if r["author"])
    by_university = Counter(f"{r['university']} ({r['country']})" for r in target_rows if r["university"])

    lines = [f"# Report Topic: {topic}", "", "## Universita piu frequenti (paesi selezionati)"]
    for uni, count in by_university.most_common(15):
        lines.append(f"- {uni}: {count} occorrenze")

    lines.extend(["", "## Professori/Autori da monitorare"])
    for (author, uni, country), count in by_author.most_common(max_authors):
        lines.append(f"- {author} ({uni}, {country}): {count} occorrenze")

    lines.extend(["", "## Nota", "Le occorrenze sono sul campione scaricato e servono come segnale iniziale, non come ranking definitivo."])
    return "\n".join(lines) + "\n"
