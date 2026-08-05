# MetaAlpha Quantum Engine — train vs infer contract

Phase 1 ships a **live ENTRY gate**. Phase 2 adds offline training
(`scripts/train_meta_alpha.py`) and a bootstrap `joblib` artifact (gitignored).
Default in `.env.example`: **OFF** (`META_ALPHA_ENABLED=false`). Local enable
requires restarting the API after changing `.env`.

## Role

- Primary side comes from A4 ENTRY: `BUY → +1`, `SELL → -1`.
- MetaAlpha answers: *should we take this primary trade?* (`proba >= threshold`)
- Does **not** invent sides. Does **not** filter SL / %TP / $TP exits.

## Frozen v1 features (12 columns)

Same names at train and live. Causal (bar `t` uses data ≤ `t`):

| Column | Definition |
|--------|------------|
| `ret_1` | `log(c_t / c_{t-1})` |
| `ret_4` | `log(c_t / c_{t-4})` |
| `ret_16` | `log(c_t / c_{t-16})` |
| `vol_20` | rolling std of `ret_1`, window 20 |
| `vol_z_100` | z-score of `vol_20` over 100 |
| `adx_14` | ADX(14) — same family as `compute_regime` |
| `di_spread_14` | `+DI(14) − −DI(14)` |
| `ema_sep_pct` | `|EMA9−EMA21| / close × 100` |
| `close_vs_ema9_pct` | `(close − EMA9) / close × 100` |
| `ema9_slope_4` | `(EMA9_t − EMA9_{t-4}) / close × 100` |
| `volume_rel_20` | `volume / SMA(volume, 20)` (or `1.0` if volume missing) |
| `hl_range_pct` | `(high − low) / close × 100` |

Joined outside the 12 (added at meta-dataset / infer time):

- `regime` ∈ `{0,1,2}` from `compute_regime(close, high, low)`
- `primary_side` ∈ `{+1, −1}`

## Live gate

`decide_take_trade(...)` → `{take, proba, regime, reason, warm}`

- Disabled → `take=1` (identity)
- Enabled + no artifact / warm-up / NaN → fail-closed (`take=0`) when
  `META_ALPHA_FAIL_CLOSED=true` (default)
- Threshold default **0.75**
- Model: optional `joblib` file under `artifacts/` (gitignored except `.gitkeep`)

Suggested artifact shapes:

```text
RegimeSwitchingMetaLabeler          # raw
{"model": <labeler>, "feature_cols": [...]}   # with column lock
```

## Barriers (labeling)

Side-aware triple barrier aligned to A4 % exits (not $70 dollar TP):

- Profit: 3% · Stop: 2% · Vertical: 32 bars on 15m
- `events["ret"] = side * (p_exit / p0 - 1)`
- Meta label: `y = 1` if `ret > fee_pad` (~0.20% round-trip pad)

## Train (Phase 2)

From `apps/api` with ML deps installed:

```bash
pip install -r requirements-ml.txt
python scripts/train_meta_alpha.py --symbol BTC --interval 15m
```

Writes `artifacts/meta_labeler.joblib` + `meta_labeler.meta.json` (both gitignored).

## Enable

1. `pip install -r apps/api/requirements-ml.txt`
2. Place trained `meta_labeler.joblib` in `artifacts/` (or set `META_ALPHA_MODEL_PATH`)
3. Set `META_ALPHA_ENABLED=true` in `.env`
4. Restart API

## Offline research

`regime_meta_cpcv.py` — leakage-safe regime + CPCV + `RegimeSwitchingMetaLabeler`.
Not invoked on the AUTO path (live gate only loads the fitted artifact).
