from __future__ import annotations

import json
import logging
import time
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from schichtwechsel.ba_client import BAClient
from schichtwechsel.config import ROOT, load_config
from schichtwechsel.details import compose, fetch_details, pending
from schichtwechsel.ingest import discover_employers, take_snapshot
from schichtwechsel.storage import Warehouse

app = typer.Typer(add_completion=False, no_args_is_help=True)
extract_app = typer.Typer(no_args_is_help=True, help="Structured fields from posting text.")
app.add_typer(extract_app, name="extract")
console = Console()

Only = Annotated[str | None, typer.Option(help="Comma separated competitor keys, e.g. dm,rossmann")]


def _keys(only: str | None) -> list[str] | None:
    return [k.strip() for k in only.split(",") if k.strip()] if only else None


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def discover(only: Only = None, pages: int = 2) -> None:
    """Show which employer names each search term returns, and which ones we keep."""
    cfg = load_config()
    with BAClient(pause=cfg.search.pause) as client:
        for comp in cfg.select(_keys(only)):
            table = Table(
                title=f"{comp.label}  ({comp.query or ', '.join(comp.employers)})",
                title_justify="left",
            )
            table.add_column("employer")
            table.add_column("postings", justify="right")
            table.add_column("kept", justify="center")
            for name, n, kept in discover_employers(comp, client, pages=pages)[:15]:
                table.add_row(name, str(n), "yes" if kept else "")
            console.print(table)


@app.command()
def snapshot(only: Only = None) -> None:
    """Pull today's postings for the configured competitors into the warehouse."""
    cfg = load_config()
    with BAClient(pause=cfg.search.pause) as client, Warehouse() as wh:
        results = take_snapshot(cfg, cfg.select(_keys(only)), client, wh)

    table = Table(title="Snapshot", title_justify="left")
    for col in ("competitor", "returned", "kept", "stored", "noise"):
        table.add_column(col, justify="left" if col == "competitor" else "right")
    for r in results:
        table.add_row(
            r.competitor, str(r.returned), str(r.kept), str(r.stored), f"{r.noise_share:.0%}"
        )
    console.print(table)


@app.command()
def profile() -> None:
    """Quick look at the latest snapshot."""
    with Warehouse() as wh:
        latest = wh.scalar("SELECT max(snapshot_date) FROM postings_snapshot")
        if latest is None:
            console.print("No snapshot yet. Run `sw snapshot` first.")
            raise typer.Exit(1)

        console.rule(f"Snapshot {latest}")
        by_type = wh.query(
            """
            SELECT competitor,
                   count(*) FILTER (WHERE offer_type = 1) AS jobs,
                   count(*) FILTER (WHERE offer_type = 4) AS apprenticeships,
                   count(DISTINCT region)                 AS regions,
                   round(avg(current_date - published_on), 1) AS avg_days_online
            FROM postings_snapshot
            WHERE snapshot_date = ?
            GROUP BY competitor
            ORDER BY jobs DESC
            """,
            [latest],
        )
        console.print(by_type.to_string(index=False))

        console.rule("Most advertised occupations")
        top = wh.query(
            """
            SELECT occupation, competitor, count(*) AS n
            FROM postings_snapshot
            WHERE snapshot_date = ? AND offer_type = 1
            GROUP BY occupation, competitor
            QUALIFY row_number() OVER (PARTITION BY competitor ORDER BY n DESC) <= 3
            ORDER BY competitor, n DESC
            """,
            [latest],
        )
        console.print(top.to_string(index=False))


@app.command()
def details(
    only: Only = None,
    per_competitor: Annotated[int, typer.Option(help="Max postings per competitor")] = 200,
) -> None:
    """Fetch the full text for postings that do not have it yet, newest first."""
    cfg = load_config()
    keys = [c.key for c in cfg.select(_keys(only))]
    with BAClient(pause=cfg.search.pause) as client, Warehouse() as wh:
        todo = pending(wh, keys, per_competitor)
        console.print(f"{len(todo)} postings to fetch")
        statuses = fetch_details(client, wh, todo)
        texts = wh.scalar("SELECT count(*) FROM posting_texts")
        with_text = wh.scalar("SELECT count(*) FROM posting_details WHERE status = 'ok'")
    console.print(f"{dict(statuses)}; {with_text} postings share {texts} distinct texts")


def _anthropic():
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    return anthropic.Anthropic()


@extract_app.command("submit")
def extract_submit(
    limit: Annotated[int, typer.Option(help="Max texts in this batch")] = 500,
) -> None:
    """Send pending texts to the Batch API."""
    from schichtwechsel.extract.runner import submit

    with Warehouse() as wh:
        batch_id = submit(_anthropic(), wh, limit)
    console.print(f"submitted {batch_id}" if batch_id else "nothing pending")


@extract_app.command("collect")
def extract_collect(
    wait: Annotated[bool, typer.Option(help="Poll until every open batch has ended")] = False,
) -> None:
    """Store results of finished batches."""
    from schichtwechsel.extract.runner import collect

    client = _anthropic()
    with Warehouse() as wh:
        while True:
            for batch_id, counts in collect(client, wh).items():
                console.print(f"{batch_id}: {dict(counts)}")
            still_open = wh.scalar(
                "SELECT count(*) FROM extraction_batches WHERE collected_at IS NULL"
            )
            if not wait or not still_open:
                break
            time.sleep(60)
    if still_open:
        console.print(f"{still_open} batch(es) still running")


@extract_app.command("status")
def extract_status() -> None:
    """Progress of the extraction for the current extractor version."""
    from schichtwechsel.extract.runner import EXTRACTOR_VERSION, MAX_CHARS

    with Warehouse() as wh:
        overview = wh.query(
            """
            SELECT
                (SELECT count(*) FROM posting_texts)                         AS texts,
                (SELECT count(*) FROM posting_features
                 WHERE extractor_version = ?)                                 AS extracted,
                (SELECT count(DISTINCT text_hash) FROM extraction_failures
                 WHERE extractor_version = ? AND reason NOT LIKE 'api:%')    AS failed,
                (SELECT count(*) FROM posting_texts WHERE chars > ?)         AS too_long,
                (SELECT count(*) FROM extraction_batches
                 WHERE collected_at IS NULL)                                 AS open_batches,
                (SELECT sum(input_tokens) FROM posting_features
                 WHERE extractor_version = ?)                                 AS input_tokens,
                (SELECT sum(output_tokens) FROM posting_features
                 WHERE extractor_version = ?)                                 AS output_tokens
            """,
            [EXTRACTOR_VERSION, EXTRACTOR_VERSION, MAX_CHARS, EXTRACTOR_VERSION, EXTRACTOR_VERSION],
        )
        console.print(f"extractor {EXTRACTOR_VERSION}")
        console.print(overview.to_string(index=False))
        reasons = wh.query(
            """
            SELECT split_part(reason, ':', 1) AS reason, count(*) AS n
            FROM extraction_failures WHERE extractor_version = ?
            GROUP BY 1 ORDER BY n DESC
            """,
            [EXTRACTOR_VERSION],
        )
        if not reasons.empty:
            console.rule("Failures")
            console.print(reasons.to_string(index=False))


@extract_app.command("one")
def extract_one_cmd(refnr: str) -> None:
    """Extract a single posting directly, without the Batch API, and print the result."""
    from schichtwechsel.extract.runner import extract_one

    with BAClient() as ba:
        raw = ba.job_details(refnr)
    text = compose(raw.get("stellenangebotsTitel"), raw.get("stellenangebotsBeschreibung"))
    if text is None:
        console.print("posting has no text")
        raise typer.Exit(1)
    outcome = extract_one(_anthropic(), text)
    if outcome.features is None:
        console.print(f"[red]{outcome.reason}[/red]")
        if outcome.raw:
            console.print(outcome.raw)
        raise typer.Exit(1)
    console.print_json(json.dumps(outcome.features.model_dump(mode="json"), ensure_ascii=False))
    console.print(f"tokens: {outcome.input_tokens} in, {outcome.output_tokens} out")


@app.command()
def check() -> None:
    """Data-quality checks on the latest snapshot. Exits 1 if any competitor dropped or vanished."""
    with Warehouse() as wh:
        health = wh.query(
            """
            SELECT competitor, postings, previous, change_pct, status
            FROM mart.snapshot_health
            WHERE snapshot_date = (SELECT max(snapshot_date) FROM postings_snapshot)
            ORDER BY competitor
            """
        )
        coverage = wh.query("SELECT * FROM mart.coverage ORDER BY open_postings DESC")
    console.print(health.to_string(index=False))
    console.rule("Coverage")
    console.print(coverage.drop(columns="note").to_string(index=False))
    for row in coverage.itertuples():
        if isinstance(row.note, str):
            console.print(f"{row.competitor}: {row.note}")
    bad = health[health["status"] != "ok"]
    if not bad.empty:
        console.print(f"[red]problems: {', '.join(bad['competitor'] + ' ' + bad['status'])}[/red]")
        raise typer.Exit(1)


@app.command()
def show(
    view: Annotated[str, typer.Argument(help="Name of a view in the mart schema")],
    limit: int = 30,
) -> None:
    """Print a mart view."""
    with Warehouse() as wh:
        views = set(
            wh.query("SELECT view_name FROM duckdb_views() WHERE schema_name = 'mart'")["view_name"]
        )
        if view not in views:
            console.print(f"unknown view; available: {', '.join(sorted(views))}")
            raise typer.Exit(1)
        frame = wh.query(f"SELECT * FROM mart.{view} LIMIT ?", [limit])
    console.print(frame.to_string(index=False))


hris_app = typer.Typer(no_args_is_help=True, help="Synthetic HR data for a fictional chain.")
app.add_typer(hris_app, name="hris")


@hris_app.command("generate")
def hris_generate(seed: int = 2026, stores: int = 300) -> None:
    """Rebuild the synthetic HR tables from the current competitor data."""
    from schichtwechsel.hris.generate import generate

    with Warehouse() as wh:
        counts = generate(wh, seed=seed, n_stores=stores)
    console.print(", ".join(f"{n:,} {name}" for name, n in counts.items()))


models_app = typer.Typer(no_args_is_help=True, help="Models on the synthetic HR data.")
app.add_typer(models_app, name="models")


@models_app.command("attrition")
def models_attrition() -> None:
    """Train and test the attrition model, score current staff, store the results."""
    from schichtwechsel.models.attrition import save, train

    with Warehouse() as wh:
        result, tables = train(wh)
        save(wh, result, tables)

    table = Table(title=f"Attrition, test {result.test}", title_justify="left")
    for col in ("model", "ROC AUC", "avg precision", "Brier", "predicted", "observed"):
        table.add_column(col, justify="left" if col == "model" else "right")
    for name in ("logistic", "boosting", "oracle", "three_month"):
        m = getattr(result, name)
        label = {"oracle": "ceiling (true drivers)", "three_month": "logistic, 3-month risk"}
        table.add_row(
            label.get(name, name),
            f"{m['roc_auc']:.3f}",
            f"{m['average_precision']:.3f}",
            f"{m['brier']:.4f}",
            f"{m['mean_predicted']:.2%}",
            f"{m['observed_rate']:.2%}",
        )
    console.print(table)
    console.rule("True vs estimated effects")
    console.print(tables["attrition_effects"].to_string(index=False))
    console.rule("Calibration by age band (age is not a model input)")
    console.print(tables["attrition_age_check"].to_string(index=False))


labels_app = typer.Typer(no_args_is_help=True, help="Hand labels and extraction accuracy.")
app.add_typer(labels_app, name="labels")
LABELS_DIR = ROOT / "labels"
Name = Annotated[str, typer.Option(help="gold (used for prompt work) or holdout (never tuned on)")]


@labels_app.command("export")
def labels_export(name: Name = "gold", force: bool = False) -> None:
    """Write a labelling workbook with a stratified sample of texts not labelled yet."""
    from schichtwechsel.extract.labels import HOLDOUT_QUOTA, QUOTA, export, hashes_in

    path = LABELS_DIR / f"{name}.xlsx"
    if path.exists() and not force:
        console.print(f"{path} exists; it may hold your labels. Use --force to replace it.")
        raise typer.Exit(1)
    taken = frozenset().union(*(hashes_in(p) for p in LABELS_DIR.glob("*.xlsx") if p != path))
    with Warehouse() as wh:
        n = export(wh, path, HOLDOUT_QUOTA if name == "holdout" else QUOTA, exclude=taken)
    console.print(f"wrote {n} postings to {path}, none of them in another label file")


@labels_app.command("score")
def labels_score(
    name: Name = "gold",
    misses: Annotated[bool, typer.Option(help="List every disagreement")] = False,
) -> None:
    """Compare finished labels with the current extraction."""
    from schichtwechsel.extract.labels import score

    with Warehouse() as wh:
        fields, benefits, n = score(wh, LABELS_DIR / f"{name}.xlsx")
    if not n:
        console.print("no block marked done yet")
        raise typer.Exit(1)

    table = Table(title=f"Accuracy on {n} labelled postings", title_justify="left")
    for col in ("field", "n", "correct", "accuracy"):
        table.add_column(col, justify="left" if col == "field" else "right")
    for key, s in fields.items():
        table.add_row(key, str(s.n), str(s.correct), f"{s.accuracy:.0%}")
    console.print(table)

    tp = sum(s.true_positives for s in benefits.values())
    fp = sum(1 for s in benefits.values() for _, want, got in s.misses if got and not want)
    fn = sum(1 for s in benefits.values() for _, want, got in s.misses if want and not got)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    console.print(
        f"benefits: precision {precision:.0%}, recall {recall:.0%} "
        f"({tp} found, {fp} extra, {fn} missed)"
    )

    if misses:
        console.rule("Disagreements (label vs. model)")
        for key, s in {**fields, **{f"benefit:{k}": v for k, v in benefits.items()}}.items():
            for who, want, got in s.misses:
                console.print(f"{key:28} {who:20} label={want!r:16} model={got!r}")


if __name__ == "__main__":
    app()
