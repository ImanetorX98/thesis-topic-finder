# Thesis Topic Finder (focus: Relativita Numerica)

Progetto automatico per:
- scaricare articoli da `arXiv` a partire da uno o piu argomenti;
- arricchire metadati con `OpenAlex`;
- catalogare per:
  - argomento;
  - professore/autore;
  - universita e paese di affiliazione;
- evidenziare i risultati legati alla Svizzera (country code `CH`).

## Requisiti
- Python 3.10+
- Connessione internet

Non richiede librerie esterne: usa solo standard library.

## Avvio rapido (relativita numerica)
```bash
cd thesis_topic_finder
python3 main.py --topics "numerical relativity" --max-results 40
```

## Confronto tra temi simili
```bash
cd thesis_topic_finder
python3 main.py --topics \
  "numerical relativity" \
  "binary black holes" \
  "gravitational wave astronomy" \
  "einstein equations" \
  --max-results 35
```

## Output
Nella cartella `data/`:
- `articles_enriched.json`: dump completo articoli + metadati OpenAlex
- `catalog.csv`: una riga per autore-affiliazione
- `topic_summary.csv`: riepilogo per topic con quota risultati svizzeri

Nella cartella `reports/`:
- `report_<topic>.md`: universita svizzere e autori piu frequenti nel campione

## Come leggere i risultati
1. Apri `data/topic_summary.csv` e ordina per `swiss_ratio`.
2. Apri il report del topic con ratio piu alta.
3. Nel `catalog.csv` filtra `is_swiss=True` per avere autori e universita svizzere.
4. Da li puoi costruire una shortlist di temi/professori da contattare per la tesi.

## Nota qualitativa
- arXiv non contiene sempre tutte le affiliazioni; OpenAlex migliora la copertura ma non e perfetto.
- Usa questo strumento come filtro iniziale, poi valida i candidati su pagine ufficiali dei gruppi di ricerca.
