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
