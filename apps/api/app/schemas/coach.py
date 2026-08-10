"""Coach signal schemas."""

from pydantic import BaseModel


class ChecklistItemResponse(BaseModel):
    id: str
    label: str
    passed: bool


class EntryFilterResultResponse(BaseModel):
    id: str
    label: str
    enabled: bool
    passed: bool
    applicable: bool = True
    reason: str = ""


class CoachSignalResponse(BaseModel):
    symbol: str
    interval: str
    signal: str  # BUY | SELL | WAIT — actionable ENTRY only
    confidence: int
    reason: str
    cofr: str
    price: str
    ema9: str | None = None
    ema21: str | None = None
    volume: str | None = None
    volume_avg20: str | None = None
    bar_closed: bool
    stop_loss: str | None = None
    take_profit: str | None = None
    risk_reward: str | None = None
    source: str
    evaluated_bar_time: int | None = None
    paper_only: bool = True
    brain: str = "DayTradeCryptoCoach"
    checklist: list[ChecklistItemResponse] = []
    short_reason: str = ""
    # ENTRY → HOLD → EXIT story
    phase: str = "NONE"  # ENTRY_BUY|ENTRY_SELL|HOLD_LONG|HOLD_SHORT|EXIT_BUY|EXIT_SELL|NONE
    position: str = "NEUTRAL"  # NEUTRAL|LONG|SHORT
    trend: str = "NONE"  # HOLD_LONG|HOLD_SHORT|NONE
    entry: str = "NONE"  # ENTRY_BUY|ENTRY_SELL|NONE
    exit: str = "NONE"  # EXIT_BUY|EXIT_SELL|NONE
    exit_reason: str | None = None  # Signal|stop_loss|take_profit
    entry_setup: str | None = None  # a4 | ccr
    entry_fill: str | None = None  # close | next_open
    entry_fill_price: str | None = None
    gross_risk_reward: str | None = None
    net_risk_reward: str | None = None
    rr_blocked: bool = False
    filter_blocked: bool = False
    filters_enabled: dict[str, bool] = {}
    filter_results: list[EntryFilterResultResponse] = []
    filter_set_id: str | None = None
    filter_version: str | None = None


class CoachSignalHistoryItem(BaseModel):
    id: int
    symbol: str
    interval: str
    brain: str
    signal: str
    entry: str
    trend: str
    phase: str | None = None
    position_state: str | None = None
    exit_kind: str | None = None
    exit_reason: str | None = None
    alert_side: str | None = None
    seq_from_entry: int | None = None
    entry_price: str | None = None
    pnl_pct_vs_entry: str | None = None
    still_profit: bool | None = None
    confidence: int
    reason: str | None = None
    short_reason: str | None = None
    cofr: str | None = None
    price: str
    ema9: str | None = None
    ema21: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    risk_reward: str | None = None
    source: str | None = None
    bar_closed: bool
    evaluated_bar_time: int
    created_at: str | None = None


class CoachSignalHistoryResponse(BaseModel):
    paper_only: bool = True
    count: int
    items: list[CoachSignalHistoryItem]


class CoachPromptResponse(BaseModel):
    name: str
    prompt: str
    min_confidence: int
    sl_pct: float
    tp_pct: float
    practice_trades_min: int
    practice_trades_target: int
    default_auto_usd: float = 100.0


class CoachStatsResponse(BaseModel):
    paper_only: bool
    closed_trades: int
    win_rate: str | None
    net_profit: str
    max_drawdown: str | None
    profit_factor: str | None
    practice_trades_min: int
    practice_trades_target: int
    practice_progress_pct: float
    ready_for_real_money_recommendation: bool
    recommendation: str
    trading_locked: bool
    lock_reason: str | None = None
    avg_win: str | None = None
    avg_loss: str | None = None
    wins: int = 0
    losses: int = 0
    last_trade_pnl: str | None = None
    last_exit_reason: str | None = None
    journaled_exits: int = 0
    avg_risk_reward: str | None = None
    planned_risk_reward: str = "1:2.5"
    strategy: str | None = None
    account_id: int | None = None
    account_name: str | None = None
    variant_stats: list[dict] = []


class CoachAutoTickResponse(BaseModel):
    paper_only: bool
    action: str
    signal: str
    confidence: int
    reason: str
    cofr: str
    order_id: int | None = None
    stats: CoachStatsResponse
    strategy: str = "A"
    brain: str | None = None
    account_id: int | None = None
    stake_usd: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    position_side: str | None = None
    logs: list[str] = []
    trend: str | None = None
    entry: str | None = None
    phase: str | None = None
    exit: str | None = None
    position_state: str | None = None
    entry_setup: str | None = None
    entry_fill: str | None = None
    entry_fill_price: str | None = None
    gross_risk_reward: str | None = None
    net_risk_reward: str | None = None
    rr_blocked: bool = False
    filter_blocked: bool = False
    filters_enabled: dict[str, bool] = {}
    filter_results: list[EntryFilterResultResponse] = []
    filter_set_id: str | None = None
    entry_source: str | None = None
    hypothesis_id: str | None = None
    hypothesis_version: str | None = None


class CoachAbTickResponse(BaseModel):
    paper_only: bool
    symbol: str
    interval: str
    market_time_shared: bool
    main_strategy: str
    note: str
    a: CoachAutoTickResponse
    b: CoachAutoTickResponse


class CoachAbCompareResponse(BaseModel):
    paper_only: bool
    main_strategy: str
    a: CoachStatsResponse
    b: CoachStatsResponse
    b_better: dict
    score_b_better_metrics: str
    promotion: dict
    conclusion: str
