# P7 amendments and deviations (found by the independent review of 2026-10-14; ML_SHADOW_PREREGISTRATION.md was NOT edited)

| # | Item | Disposition |
|---|---|---|
| M1 | Baseline B1 | The pre-registration says "momentum: probability from the SIGN of the last 4-bar return". The code fits a logistic on the 4-bar return divided by ATR (the MAGNITUDE feature `ret4_atr`). A monotone logistic on that single feature gives the same ranking (AUC) as the sign for the direction it learns, but not the same probabilities. Disclosed; the reported B1 AUC (0.497) is for the magnitude version. |
| M2 | Walk-forward embargo | Inside development, expanding-window training samples are purged by horizon (their 4-bar future ends before the test block) but there is NO additional 24 h embargo (the 24 h gap exists only between development and validation). Disclosed; the walk-forward AUCs (0.494-0.511) are noise-level either way. |
| M3 | `holdout_loaded` flag | It was a hard-coded literal in the result metadata. It is now computed from the loaded bars (any bar closing after the frozen `val_end`). The runner still reads all bars from the store and drops the holdout bars before any feature is built (`cut_bars`); no holdout bar enters a computation. |
| M4 | Result | Unchanged: NO_EVIDENCE_OF_PREDICTIVE_SKILL (validation AUC 0.499). The review confirmed no leakage: features at the validation cut equal the features on the longer series for all 13 930 overlapping rows. |
