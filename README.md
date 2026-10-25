# Schichtwechsel

Hiring and workforce intelligence for German drugstore retail.

*Schichtwechsel* means shift change. In a store business, people changing shifts is routine; people changing employers is the expensive part. This project looks at both sides: who competitors are hiring right now, and which of your own people are likely to leave.

> Independent portfolio project. Not affiliated with or endorsed by any of the companies named. Employee data used in this project is synthetic.

[Deutsch weiter unten](#kurzfassung-auf-deutsch)

## Status

| Part | State |
|---|---|
| Daily snapshot of competitor job postings (BA Jobsuche) | working |
| Structured extraction from posting text with Claude | working, backfill pending |
| Analytics views: hiring pressure, pay, benefits, data quality | working |
| Synthetic HR data, attrition and time-to-fill models | planned |
| Analyst agent with guardrails, DE/EN | planned |
| Web app and Azure deployment | planned |

## Setup

Requires [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda.

```bash
conda env create -f environment.yml
conda activate schichtwechsel
pytest
```

The environment installs the project in editable mode, so `sw` is available as a command and code changes apply without reinstalling.

In VS Code: `Ctrl+Shift+P` > *Python: Select Interpreter* > `schichtwechsel`.

## Usage

```bash
sw discover --only dm,rossmann   # which employer names does each search term hit?
sw snapshot                      # pull today's postings for all competitors
sw profile                       # quick summary of the latest snapshot

sw details --per-competitor 200  # fetch full text for postings not seen yet
sw extract submit                # send pending texts to the Batch API
sw extract collect --wait        # store results once the batch has ended
sw extract status                # progress, failures, token use
sw extract one <refnr>           # one posting, sent directly, for prompt work

sw labels score --name holdout   # extraction accuracy on hand labels
sw check                         # data quality; exits 1 if a competitor dropped or vanished
sw show hiring_pressure          # print any view in the mart schema
```

Extraction needs an Anthropic API key: copy `.env.example` to `.env` and fill it in.

Competitors and search terms live in `config/competitors.yaml`.

## Data

Postings come from the job search of the Bundesagentur für Arbeit, accessed through the community-documented API at [jobsuche.api.bund.dev](https://jobsuche.api.bund.dev). There is no official API, so endpoints may change. The client pauses between requests and retries with backoff; please keep it that way.

Each run stores:

- `data/raw/<date>/` the untouched API responses (gzip JSON lines)
- `data/warehouse.duckdb` a `postings_snapshot` table, one row per posting per day, plus a `posting_lifecycle` view

Design decisions are recorded in [`docs/adr`](docs/adr).

## Kurzfassung auf Deutsch

*Schichtwechsel* analysiert den Stellenmarkt im Drogerie- und Lebensmitteleinzelhandel. Täglich werden die Stellenangebote von dm, Rossmann, Müller, Budni, Lidl, Aldi und Kaufland aus der Jobsuche der Bundesagentur für Arbeit gesichert. Aus den täglichen Momentaufnahmen entsteht eine Zeitreihe: Wie lange bleiben Stellen online, wo steigt der Personalbedarf, wer sucht wie viele Auszubildende?

Geplant sind außerdem ein synthetischer Personaldatensatz mit Fluktuationsmodell sowie ein zweisprachiger Analyse-Assistent auf Basis von Claude, abgesichert durch Guardrails für Datenschutz und SQL-Zugriff.

Unabhängiges Portfolio-Projekt, keine Verbindung zu den genannten Unternehmen.

## License

MIT
