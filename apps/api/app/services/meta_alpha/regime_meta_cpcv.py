"""
regime_meta_cpcv.py
-------------------
Leakage-safe Regime-Switching Meta-Labeling
+ Combinatorial Purged Cross-Validation
+ Sample Uniqueness Weighting
"""

import numpy as np
import pandas as pd
from itertools import combinations
from typing import Generator, Tuple, Optional, Dict
from math import comb
from sklearn.ensemble import RandomForestClassifier

# ==============================================================================
# 1. Causal regime detection (safe to compute on full series)
# ==============================================================================

def compute_regime(
    close: pd.Series,
    high: Optional[pd.Series] = None,
    low: Optional[pd.Series] = None,
    window_adx: int = 14,
    window_vol: int = 20,
    vol_lookback: int = 100,
) -> pd.Series:
    """
    Fully causal regime labels.
    0 = Range/Low-vol, 1 = Trend/Normal, 2 = High-vol/Crisis
    """
    high = high if high is not None else close
    low  = low  if low  is not None else close

    up = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(window_adx).mean()
    plus_di  = 100 * pd.Series(plus_dm, index=close.index).rolling(window_adx).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(window_adx).mean() / atr
    dx  = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
    adx = dx.rolling(window_adx).mean()

    vol = close.pct_change().rolling(window_vol).std()
    vol_rank = vol.rolling(vol_lookback).rank(pct=True)

    regime = pd.Series(1, index=close.index, name="regime")
    regime[adx < 20] = 0
    regime[vol_rank > 0.80] = 2
    return regime

# ==============================================================================
# 2. Uniqueness + purge helpers (from earlier hardened versions)
# ==============================================================================

def get_avg_uniqueness_fold(t1: pd.Series, train_times: pd.DatetimeIndex) -> pd.Series:
    t1_train = t1.loc[t1.index.isin(train_times)].sort_index()
    if t1_train.empty:
        return pd.Series(dtype=float)

    n_bars = len(train_times)
    start_pos = np.clip(train_times.searchsorted(t1_train.index.values), 0, n_bars)
    end_pos   = np.clip(train_times.searchsorted(t1_train.values, side="right") - 1, -1, n_bars-1)

    concurrency = np.zeros(n_bars + 1, dtype=float)
    for s, e in zip(start_pos, end_pos):
        if s >= n_bars or e < 0:
            continue
        s, e = max(s, 0), min(e, n_bars-1)
        if s <= e:
            concurrency[s] += 1.0
            concurrency[e+1] -= 1.0

    concurrency = np.cumsum(concurrency[:-1])
    concurrency[concurrency == 0] = np.nan

    avg_u = np.zeros(len(t1_train))
    for i, (s, e) in enumerate(zip(start_pos, end_pos)):
        if s >= n_bars or e < 0:
            continue
        s, e = max(s, 0), min(e, n_bars-1)
        if s <= e:
            avg_u[i] = np.nanmean(1.0 / concurrency[s:e+1])
    return pd.Series(avg_u, index=t1_train.index)

def get_sample_weights_fold(
    t1: pd.Series,
    train_times: pd.DatetimeIndex,
    returns: Optional[pd.Series] = None,
    time_decay: float = 1.0,
) -> pd.Series:
    avg_u = get_avg_uniqueness_fold(t1, train_times)
    if avg_u.empty:
        return pd.Series(dtype=float)
    w = avg_u * returns.reindex(avg_u.index).abs().fillna(0.0) if returns is not None else avg_u
    if 0 < time_decay < 1 and len(w) > 1:
        w *= np.linspace(time_decay, 1.0, len(w))
    total = w.sum()
    if total > 0:
        w *= len(w) / total
    return w

def get_purge_mask(t1: pd.Series, test_times: pd.DatetimeIndex) -> pd.Series:
    test_start = test_times.min()
    test_end   = t1.reindex(test_times).max()
    return (t1.index <= test_end) & (t1 >= test_start)

# ==============================================================================
# 3. Combinatorial Purged CV (with date bounds + weights)
# ==============================================================================

class CombinatorialPurgedCV:
    def __init__(self, n_groups: int = 6, n_test_groups: int = 2, embargo_pct: float = 0.01):
        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.embargo_pct = embargo_pct

    def split(
        self,
        X: pd.DataFrame,
        t1: pd.Series,
        returns: Optional[pd.Series] = None,
        time_decay: float = 1.0,
    ) -> Generator[Tuple[np.ndarray, np.ndarray, np.ndarray, int, pd.Timestamp, pd.Timestamp], None, None]:
        n = len(X)
        indices = np.arange(n)
        times = X.index
        t1 = t1.reindex(times).ffill()

        group_size = n // self.n_groups
        groups = [indices[i*group_size:(i+1)*group_size] for i in range(self.n_groups-1)]
        groups.append(indices[(self.n_groups-1)*group_size:])

        embargo = int(n * self.embargo_pct)
        combos = list(combinations(range(self.n_groups), self.n_test_groups))

        for path_id, test_gids in enumerate(combos):
            test_idx = np.hstack([groups[g] for g in test_gids])
            train_mask = np.ones(n, dtype=bool)
            train_mask[test_idx] = False

            for g in test_gids:
                end = groups[g][-1] + 1
                train_mask[end:min(end+embargo, n)] = False

            test_times = times[test_idx]
            purge = get_purge_mask(t1, test_times)
            train_mask[purge.reindex(times).fillna(False).values] = False

            train_idx = np.setdiff1d(indices[train_mask], test_idx)
            train_times = times[train_idx]

            weights = get_sample_weights_fold(t1, train_times, returns, time_decay)
            weights = weights.reindex(train_times).fillna(0.0)

            valid = weights.values > 0
            if not valid.any():
                continue

            yield (
                train_idx[valid],
                test_idx,
                weights.values[valid],
                path_id,
                test_times.min(),
                test_times.max(),
            )

    def get_n_splits(self) -> int:
        return comb(self.n_groups, self.n_test_groups)

# ==============================================================================
# 4. Meta-dataset builder (regime is pre-computed & causal)
# ==============================================================================

def build_meta_dataset(
    primary_side: pd.Series,
    events: pd.DataFrame,
    features: pd.DataFrame,
    regime: pd.Series,
) -> Tuple[pd.DataFrame, pd.Series]:
    common = primary_side.index.intersection(events.index).intersection(features.index)
    side = primary_side.loc[common]
    ev   = events.loc[common]
    feat = features.loc[common]

    # Meta-label: did the primary side prove correct?
    meta_y = (np.sign(ev["ret"]) == side).astype(int)

    meta_X = feat.copy()
    meta_X["regime"] = regime.reindex(common).ffill()
    meta_X["primary_side"] = side

    mask = meta_X.notna().all(axis=1) & meta_y.notna()
    return meta_X.loc[mask], meta_y.loc[mask]

# ==============================================================================
# 5. Regime-switching meta-labeler
# ==============================================================================

class RegimeSwitchingMetaLabeler:
    def __init__(self, mode: str = "feature", **rf_params):
        self.mode = mode
        self.rf_params = rf_params or {"n_estimators": 200, "max_depth": 6, "n_jobs": -1}
        self.model = None
        self.models: Dict[int, object] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: Optional[np.ndarray] = None):
        if self.mode == "feature":
            self.model = RandomForestClassifier(**self.rf_params)
            self.model.fit(X, y, sample_weight=sample_weight)
        else:
            for r in X["regime"].unique():
                m = X["regime"] == r
                if m.sum() < 40:
                    continue
                clf = RandomForestClassifier(**self.rf_params)
                clf.fit(X.loc[m].drop(columns=["regime"]), y.loc[m],
                        sample_weight=None if sample_weight is None else sample_weight[m])
                self.models[int(r)] = clf
        return self

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        if self.mode == "feature":
            p = self.model.predict_proba(X)[:, 1]
            return pd.Series(p, index=X.index, name="meta_proba")

        p = pd.Series(0.5, index=X.index)
        for r, clf in self.models.items():
            m = X["regime"] == r
            if m.any():
                p.loc[m] = clf.predict_proba(X.loc[m].drop(columns=["regime"]))[:, 1]
        return p.rename("meta_proba")

# ==============================================================================
# 6. Full leakage-safe CPCV + meta-labeling loop
# ==============================================================================

def run_regime_meta_cpcv(
    meta_X: pd.DataFrame,
    meta_y: pd.Series,
    t1: pd.Series,
    returns: pd.Series,
    n_groups: int = 6,
    n_test_groups: int = 2,
    time_decay: float = 1.0,
):
    """
    Executes Combinatorial Purged CV on the meta-labeling problem.
    Regime features are already causal → no leakage.
    """
    cpcv = CombinatorialPurgedCV(n_groups=n_groups, n_test_groups=n_test_groups)
    results = []

    for train_idx, test_idx, sw, path_id, t_start, t_end in cpcv.split(
        meta_X, t1, returns=returns, time_decay=time_decay
    ):
        X_tr, y_tr = meta_X.iloc[train_idx], meta_y.iloc[train_idx]
        X_te, y_te = meta_X.iloc[test_idx],  meta_y.iloc[test_idx]

        meta_model = RegimeSwitchingMetaLabeler(mode="feature")
        meta_model.fit(X_tr, y_tr, sample_weight=sw)

        proba = meta_model.predict_proba(X_te)
        # Example metric: average precision or accuracy at threshold 0.55
        pred  = (proba >= 0.55).astype(int)
        acc   = (pred == y_te).mean()

        results.append({
            "path_id": path_id,
            "test_start": t_start,
            "test_end": t_end,
            "accuracy": acc,
            "mean_proba": proba.mean(),
        })

    return pd.DataFrame(results)
