# Paper Crypto Coach — User Guide

In-app guide (recommended): sign in and open **[/guide](/guide)** (Help icon in the header, or **Settings → Open User Guide**).

Illustrations live in `apps/web/public/guide/`.

## Lab → AUTO (important)

Paper signals and AUTO use **Hypothesis Lab** profiles only:

1. **Lab** — prompt → generate version → backtest → save paper profile  
2. **Settings** — interval, stake, leverage, SL/TP for AUTO risk  
3. **Market** or **Coach** — choose the promoted profile, turn AUTO on, keep the page open  
4. Review in **Portfolio / History / Journal / Analytics**

![Lab to AUTO flow](apps/web/public/guide/lab-auto-flow.svg)

AUTO evaluates closed candles and fills eligible longs at the next candle open.

---

## Dashboard

![Dashboard](apps/web/public/guide/dashboard.svg)

- **For:** Portfolio overview, P&L, equity path, open positions.  
- **Do:** Scan daily risk, then jump to Market.  
- **Connects:** Summarizes Portfolio and History.

## Market

![Market](apps/web/public/guide/market.svg)

- **For:** Charts + Lab paper AUTO per symbol.  
- **Do:** Pick symbol → choose promoted Lab profile → AUTO on (or Manual ticket).  
- **Connects:** Profiles from Lab; risk from Settings; fills → Portfolio/History.

## Desk

![Desk](apps/web/public/guide/desk.svg)

- **For:** Simple manual Buy/Sell paper practice.  
- **Do:** Size notional and trade.  
- **Connects:** Independent of Lab AUTO; still feeds History/Analytics.

## Portfolio

![Portfolio](apps/web/public/guide/portfolio.svg)

- **For:** Open holdings, allocation, unrealized P&L.  
- **Do:** Inspect lots before adding risk.  
- **Connects:** Desk + Lab AUTO fills.

## History

![History](apps/web/public/guide/history.svg)

- **For:** All paper fills with filters.  
- **Do:** Review winners/losers and fees.  
- **Connects:** Feeds Analytics; pairs with Journal.

## Journal

![Journal](apps/web/public/guide/journal.svg)

- **For:** Setup notes and emotion tags.  
- **Do:** Log after important trades.  
- **Connects:** Emotion breakdowns in Analytics.

## Coach

![Coach](apps/web/public/guide/coach.svg)

- **For:** Practice stats + same Lab AUTO desk as Market.  
- **Do:** Select promoted profile, keep page open for ticks.  
- **Connects:** Lab profiles only. Outcomes → Portfolio/History.

## Lab

![Lab](apps/web/public/guide/lab.svg)

- **For:** Research hypotheses into immutable paper profiles.  
- **Do:** Prompt → Generate → Backtest (0.80% fees) → Save paper profile.  
- **Connects:** Only promoted profiles drive Market/Coach AUTO.

## Analytics

![Analytics](apps/web/public/guide/analytics.svg)

- **For:** Expectancy, PF, drawdown, by asset / by emotion.  
- **Do:** Decide which Lab profiles deserve more paper size.  
- **Connects:** History + Journal.

## Settings

![Settings](apps/web/public/guide/settings.svg)

- **For:** Risk limits and coach AUTO defaults; paper reset.  
- **Do:** Set interval/stake/SL/TP; open User Guide from here.  
- **Connects:** Risk for AUTO; entry rules still come from Lab.

---

English-only UI. Paper trading only — never real funds.
