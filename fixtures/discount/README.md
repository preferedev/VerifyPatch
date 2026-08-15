The discount fixture models an implementation change that also weakens tests.

Base: `final_price` and `restock` with strict tests.
Head: production behavior changes, a new unimported `promo.py`, skipped/weakened inventory tests, and untouched pricing tests.

Expected provenance:
- new executable lines in `src/pricing.py` covered by PR-untouched tests
- new executable lines in `src/inventory.py` covered only by PR-touched tests
- new executable lines in `src/promo.py` uncovered (never imported)
