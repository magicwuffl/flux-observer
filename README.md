# Observer – Marktbeobachtung Pumpenindustrie

Automatisierte Marktbeobachtung für FLUX-GERÄTE GMBH. Ein Claude Code Scheduled Agent recherchiert 3x pro Woche aktuelle Entwicklungen in der Pumpenindustrie und erstellt strukturierte Markdown-Reports.

## Reports

- **Mo, Mi, Fr:** Kompakte Tagesberichte in `reports/daily/`
- **Freitags:** Wochen-Digest mit Trend-Bewertung in `reports/weekly/`
- **Monatlich:** B2B-Portal-Check + Monatsrückblick in `reports/monthly/`

## Scope

- 14 Wettbewerber (direkt + Technologie)
- Fachmedien DE + EN + FR
- Kernbranchen: Chemie, Pharma, Food
- Rollenspezifische Empfehlungen: Marketing, Vertrieb/ADM, Produktentwicklung, GF

## Konfiguration

Alle Recherche-Parameter in `config/`:
- `competitors.md` – Wettbewerber mit Websites
- `sources.md` – Informationsquellen & Fachmedien
- `keywords.md` – Suchbegriffe (DE/EN/FR)
- `roles.md` – Rollen-Definitionen
- `news-sources.yaml` – RSS/HTML-Endpunkte fuer den Direktquellen-Scraper

## Direktquellen-Scraper (RSS-First)

Vor jedem Agent-Lauf laeuft eine GitHub Action (Mo/Mi/Fr 06:00 UTC):

```
.github/workflows/scrape-news.yml  → scrapers/scrape_competitors.py
```

Der Scraper holt News-Items von Wettbewerber-Listings und **FLUX selbst** (Self-Monitoring) als JSON nach `incoming/YYYY-MM-DD/<slug>.json`. Strategie:

1. RSS-Feed direkt (Config-Eintrag `rss`)
2. Auto-Discovery via `<link rel="alternate" type="application/rss+xml">`
3. HTML-Heuristik mit optionalem `link_pattern` (Regex auf Article-URLs)

State: `state/<slug>.json` – schon gesehene Items werden ausgefiltert. Quellen mit Bot-Schutz (NETZSCH, SEEPEX, Graco, ARO, IST Pumpen) bleiben `enabled: false`; der Agent deckt sie weiter via Web-Suche ab.

Manueller Test:

```bash
pip install -r scrapers/requirements.txt
python scrapers/scrape_competitors.py                 # alle Quellen
python scrapers/scrape_competitors.py --source flux-news --no-state   # einzelner Slug, ohne State
```
