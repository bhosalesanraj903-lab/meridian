# Source catalog (verified endpoints)

| Source | Endpoint | Cadence | Auth | Known quirks |
|---|---|---|---|---|
| OFAC SDN | treasury.gov/ofac/downloads/sdn.csv | irregular, often weekly+ | none | change-detect via hash; new designation => full rescan SLA 4h |
| SEC EDGAR | /Archives/edgar/daily-index + data.sec.gov | daily; Sat index rebuild | User-Agent required | 10 req/s hard limit; post-acceptance corrections => restatements |
| FFIEC Call Reports | CDR bulk per quarter | quarterly | none/registration | schedule line items redefined across years; amended filings |
| FDIC BankFind | banks.data.fdic.gov API | event-driven | none | feeds dim_institution; mergers/failures |
| GSE loan perf | Fannie/Freddie downloads | quarterly | free registration | tens of GB; pipe-delimited; monthly performance rows |
| Binance | wss://data-stream.binance.vision/ws/{sym}@trade | realtime | none | 24h forced disconnect; 3-min ping/pong; REST klines for backfill |
| Treasury yields / SOFR | treasury.gov, NY Fed | daily | none | reference dims |
| FRED | api.stlouisfed.org | per-series | free key | macro enrichment |
