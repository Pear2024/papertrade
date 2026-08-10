import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "guide");
fs.mkdirSync(outDir, { recursive: true });

function frame(title, activeNav, body) {
  const nav = [
    "Dashboard",
    "Market",
    "Desk",
    "Portfolio",
    "History",
    "Journal",
    "Coach",
    "Lab",
    "Analytics",
    "Settings",
  ];
  const pills = nav
    .map((n, i) => {
      const x = 16 + i * 94;
      const on = n === activeNav;
      return `<rect x="${x}" y="52" width="88" height="28" rx="6" fill="${on ? "#d6eef8" : "#f1f5f9"}" stroke="${on ? "#0b7ea8" : "#d0d7e2"}"/>
    <text x="${x + 44}" y="70" text-anchor="middle" font-size="11" font-family="Segoe UI,Arial,sans-serif" fill="${on ? "#086484" : "#64748b"}">${n}</text>`;
    })
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#e8f6fc"/>
      <stop offset="55%" stop-color="#f8fafc"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#bg)"/>
  <rect x="0" y="0" width="960" height="88" fill="#ffffff" stroke="#e2e8f0"/>
  <text x="24" y="30" font-size="16" font-weight="700" font-family="Segoe UI,Arial,sans-serif" fill="#0f172a">Paper Crypto Coach</text>
  <text x="900" y="30" text-anchor="end" font-size="12" font-family="Segoe UI,Arial,sans-serif" fill="#64748b">Paper only</text>
  ${pills}
  <text x="24" y="120" font-size="22" font-weight="700" font-family="Segoe UI,Arial,sans-serif" fill="#0f172a">${title}</text>
  ${body}
  <text x="24" y="525" font-size="11" font-family="Segoe UI,Arial,sans-serif" fill="#94a3b8">UI illustration · Paper Crypto Coach User Guide</text>
</svg>`;
}

function card(x, y, w, h, label, value, sub = "") {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="#fff" stroke="#dbe3ee"/>
  <text x="${x + 14}" y="${y + 24}" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">${label}</text>
  <text x="${x + 14}" y="${y + 52}" font-size="20" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">${value}</text>
  ${sub ? `<text x="${x + 14}" y="${y + 74}" font-size="11" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">${sub}</text>` : ""}`;
}

const files = {
  "dashboard.svg": frame(
    "Dashboard",
    "Dashboard",
    card(24, 140, 210, 90, "Portfolio Value", "$20,842.10") +
      card(250, 140, 210, 90, "Cash Balance", "$12,400.00") +
      card(476, 140, 210, 90, "Unrealized P&amp;L", "+$184.20") +
      card(702, 140, 210, 90, "Win Rate", "58.3%") +
      `<rect x="24" y="250" width="560" height="230" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="40" y="278" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Portfolio value</text>
     <path d="M50 430 C120 400,180 360,250 370 C320 380,380 300,460 290 C520 284,540 310,560 300" fill="none" stroke="#0b7ea8" stroke-width="3"/>
     <path d="M50 430 C120 400,180 360,250 370 C320 380,380 300,460 290 C520 284,540 310,560 300 L560 450 L50 450 Z" fill="#0b7ea8" opacity="0.12"/>
     <rect x="604" y="250" width="332" height="230" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="620" y="278" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Open positions</text>
     <text x="620" y="318" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">BTC · long · +$92.40</text>
     <text x="620" y="348" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">ETH · long · −$18.10</text>
     <text x="620" y="390" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Quick jump → Market</text>`,
  ),
  "market.svg": frame(
    "Market",
    "Market",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Lab paper AUTO on any listed coin — pick a matching promoted profile.</text>
     <rect x="24" y="168" width="52" height="28" rx="6" fill="#0b7ea8"/><text x="50" y="187" text-anchor="middle" font-size="12" fill="#fff" font-family="Segoe UI,Arial,sans-serif">BTC</text>
     <rect x="84" y="168" width="52" height="28" rx="6" fill="#fff" stroke="#d0d7e2"/><text x="110" y="187" text-anchor="middle" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">ETH</text>
     <rect x="144" y="168" width="52" height="28" rx="6" fill="#fff" stroke="#d0d7e2"/><text x="170" y="187" text-anchor="middle" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">SOL</text>
     <rect x="780" y="168" width="156" height="28" rx="6" fill="#e2e8f0"/><text x="858" y="187" text-anchor="middle" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Manual ticket · BTC</text>
     <rect x="24" y="214" width="560" height="260" rx="12" fill="#0f172a"/>
     <path d="M50 400 L110 360 L170 380 L240 300 L310 320 L390 250 L470 270 L540 220" fill="none" stroke="#38bdf8" stroke-width="2"/>
     <text x="40" y="240" font-size="12" fill="#94a3b8" font-family="Segoe UI,Arial,sans-serif">15m chart</text>
     <rect x="600" y="214" width="336" height="260" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="618" y="244" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">BTC · Lab paper AUTO</text>
     <rect x="618" y="260" width="80" height="22" rx="11" fill="#0b7ea8"/><text x="658" y="275" text-anchor="middle" font-size="11" fill="#fff" font-family="Segoe UI,Arial,sans-serif">AUTO ON</text>
     <text x="618" y="312" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Lab profile</text>
     <rect x="618" y="322" width="200" height="28" rx="6" fill="#f8fafc" stroke="#d0d7e2"/>
     <text x="630" y="341" font-size="12" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">EMA Cross v2</text>
     <rect x="618" y="372" width="300" height="70" rx="8" fill="#ecfdf5" stroke="#86efac"/>
     <text x="632" y="402" font-size="13" font-weight="600" fill="#047857" font-family="Segoe UI,Arial,sans-serif">WAIT · closed candle</text>
     <text x="632" y="424" font-size="11" fill="#065f46" font-family="Segoe UI,Arial,sans-serif">Promote in Lab → choose profile → AUTO</text>`,
  ),
  "desk.svg": frame(
    "Desk",
    "Desk",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Simple Buy / Sell desk for paper practice — fills stay simulated.</text>
     <rect x="24" y="168" width="48" height="26" rx="6" fill="#0b7ea8"/><text x="48" y="186" text-anchor="middle" font-size="11" fill="#fff" font-family="Segoe UI,Arial,sans-serif">BTC</text>
     <rect x="80" y="168" width="48" height="26" rx="6" fill="#fff" stroke="#d0d7e2"/><text x="104" y="186" text-anchor="middle" font-size="11" fill="#334155" font-family="Segoe UI,Arial,sans-serif">ETH</text>
     <rect x="24" y="214" width="440" height="260" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="44" y="248" font-size="16" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Buy BTC</text>
     <rect x="44" y="270" width="380" height="40" rx="8" fill="#f8fafc" stroke="#d0d7e2"/>
     <text x="58" y="295" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Notional USD</text>
     <rect x="44" y="330" width="180" height="48" rx="8" fill="#059669"/><text x="134" y="360" text-anchor="middle" font-size="15" font-weight="600" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Buy</text>
     <rect x="236" y="330" width="180" height="48" rx="8" fill="#dc2626"/><text x="326" y="360" text-anchor="middle" font-size="15" font-weight="600" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Sell</text>
     <rect x="488" y="214" width="448" height="260" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="508" y="248" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Position snapshot</text>
     <text x="508" y="286" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Qty 0.12 BTC · Entry $64,210</text>
     <text x="508" y="316" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Unrealized +$42.10</text>
     <text x="508" y="360" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Manual practice · no Lab AUTO required</text>`,
  ),
  "portfolio.svg": frame(
    "Portfolio",
    "Portfolio",
    card(24, 140, 300, 90, "Portfolio Value", "$20,842.10", "Cash $12,400") +
      card(340, 140, 300, 90, "Unrealized P&amp;L", "+$184.20", "Across open lots") +
      card(656, 140, 280, 90, "Positions", "2 open", "Allocation shown below") +
      `<rect x="24" y="250" width="912" height="220" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="40" y="280" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Holdings</text>
     <text x="40" y="320" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Symbol   Qty        Entry        Mark         U.P&amp;L      Alloc</text>
     <line x1="40" y1="332" x2="910" y2="332" stroke="#e2e8f0"/>
     <text x="40" y="360" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">BTC      0.12       64210        64980        +$92       38%</text>
     <text x="40" y="392" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">ETH      1.80       3420         3398         −$40       29%</text>
     <text x="40" y="440" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Fed by Desk buys and Lab AUTO fills · review Journal after closes</text>`,
  ),
  "history.svg": frame(
    "History",
    "History",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Every paper fill — filter by symbol, side, P&amp;L, and date.</text>
     <rect x="24" y="168" width="140" height="34" rx="8" fill="#fff" stroke="#d0d7e2"/><text x="38" y="190" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Symbol: all</text>
     <rect x="176" y="168" width="140" height="34" rx="8" fill="#fff" stroke="#d0d7e2"/><text x="190" y="190" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Side: all</text>
     <rect x="328" y="168" width="140" height="34" rx="8" fill="#fff" stroke="#d0d7e2"/><text x="342" y="190" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">P&amp;L: all</text>
     <rect x="24" y="220" width="912" height="250" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="40" y="250" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Time                 Symbol   Side    Qty      Price      Fee      Realized</text>
     <line x1="40" y1="262" x2="910" y2="262" stroke="#e2e8f0"/>
     <text x="40" y="292" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Aug 9 14:02          BTC      BUY     0.05     64820      $5.18    —</text>
     <text x="40" y="324" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Aug 9 15:41          BTC      SELL    0.05     65110      $5.21    +$9.20</text>
     <text x="40" y="356" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Aug 9 16:08          ETH      BUY     0.80     3410       $2.18    —</text>
     <text x="40" y="420" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Includes manual Desk trades and Lab AUTO entries/exits</text>`,
  ),
  "journal.svg": frame(
    "Journal",
    "Journal",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Reflect on setups and emotions — links learning to Analytics.</text>
     <rect x="24" y="170" width="440" height="300" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="44" y="202" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">New entry</text>
     <rect x="44" y="220" width="180" height="34" rx="8" fill="#f8fafc" stroke="#d0d7e2"/><text x="58" y="242" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Symbol: BTC</text>
     <rect x="236" y="220" width="200" height="34" rx="8" fill="#f8fafc" stroke="#d0d7e2"/><text x="250" y="242" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Setup: Lab EMA</text>
     <rect x="44" y="270" width="392" height="90" rx="8" fill="#f8fafc" stroke="#d0d7e2"/>
     <text x="58" y="298" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Notes: waited for closed 15m bar…</text>
     <text x="44" y="390" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Emotion tags: calm · confident</text>
     <rect x="44" y="410" width="140" height="36" rx="8" fill="#0b7ea8"/><text x="114" y="433" text-anchor="middle" font-size="13" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Save entry</text>
     <rect x="488" y="170" width="448" height="300" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="508" y="202" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Recent notes</text>
     <rect x="508" y="220" width="408" height="70" rx="8" fill="#f8fafc" stroke="#e2e8f0"/>
     <text x="522" y="248" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">BTC · Lab profile fill</text>
     <text x="522" y="270" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Emotion: calm · followed checklist</text>
     <rect x="508" y="306" width="408" height="70" rx="8" fill="#f8fafc" stroke="#e2e8f0"/>
     <text x="522" y="334" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">ETH · Desk scalp</text>
     <text x="522" y="356" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Emotion: impatient · cut early</text>`,
  ),
  "coach.svg": frame(
    "Coach",
    "Coach",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Lab paper AUTO — same desk as Market. Hypothesis Lab prompts drive entries.</text>
     <rect x="24" y="168" width="210" height="70" rx="10" fill="#fff" stroke="#dbe3ee"/><text x="40" y="196" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Win rate</text><text x="40" y="220" font-size="18" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">54.2%</text>
     <rect x="250" y="168" width="210" height="70" rx="10" fill="#fff" stroke="#dbe3ee"/><text x="266" y="196" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Paper trades</text><text x="266" y="220" font-size="18" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">86 / 200</text>
     <rect x="476" y="168" width="210" height="70" rx="10" fill="#fff" stroke="#dbe3ee"/><text x="492" y="196" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Net profit</text><text x="492" y="220" font-size="18" font-weight="700" fill="#059669" font-family="Segoe UI,Arial,sans-serif">$412.08</text>
     <rect x="702" y="168" width="234" height="70" rx="10" fill="#fff" stroke="#dbe3ee"/><text x="718" y="196" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Max drawdown</text><text x="718" y="220" font-size="18" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">$286.40</text>
     <rect x="24" y="260" width="912" height="200" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="44" y="292" font-size="15" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">BTC · Lab paper AUTO</text>
     <rect x="860" y="274" width="56" height="22" rx="11" fill="#0b7ea8"/><text x="888" y="289" text-anchor="middle" font-size="11" fill="#fff" font-family="Segoe UI,Arial,sans-serif">AUTO</text>
     <text x="44" y="328" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">1. Promote profile in Lab · 2. Select it here · 3. Keep page open for ticks</text>
     <rect x="44" y="350" width="280" height="36" rx="8" fill="#f8fafc" stroke="#d0d7e2"/><text x="58" y="373" font-size="12" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Profile: RSI Pullback v1</text>
     <rect x="44" y="400" width="320" height="40" rx="8" fill="#059669"/><text x="204" y="425" text-anchor="middle" font-size="13" font-weight="600" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Turn AUTO on</text>`,
  ),
  "lab.svg": frame(
    "Lab",
    "Lab",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Turn a rule idea into an immutable paper-research version. A4/CCR built-ins are retired.</text>
     <rect x="24" y="168" width="912" height="54" rx="10" fill="#eff6ff" stroke="#bfdbfe"/>
     <text x="40" y="200" font-size="13" fill="#1e40af" font-family="Segoe UI,Arial,sans-serif">Flow: Prompt → Generate version → Backtest → Save paper profile → AUTO on Market/Coach</text>
     <rect x="24" y="240" width="440" height="220" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="44" y="270" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Describe a hypothesis</text>
     <rect x="44" y="288" width="400" height="100" rx="8" fill="#f8fafc" stroke="#d0d7e2"/>
     <text x="58" y="318" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">BTCUSDT 15m: EMA9 &gt; EMA21, 1h &gt; EMA200,</text>
     <text x="58" y="338" font-size="12" fill="#334155" font-family="Segoe UI,Arial,sans-serif">volume &gt; 1.5x, RSI 50–70, stop 1 ATR, 2R</text>
     <rect x="44" y="408" width="220" height="36" rx="8" fill="#0b7ea8"/><text x="154" y="431" text-anchor="middle" font-size="13" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Generate testable version</text>
     <rect x="488" y="240" width="448" height="220" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="508" y="270" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">EMA Cross v2</text>
     <text x="780" y="270" font-size="11" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Parsed by rules</text>
     <text x="508" y="304" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Verdict: PASS · 142 trades · fees 0.80%</text>
     <rect x="508" y="328" width="120" height="34" rx="8" fill="#0b7ea8"/><text x="568" y="350" text-anchor="middle" font-size="12" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Backtest</text>
     <rect x="640" y="328" width="160" height="34" rx="8" fill="#fff" stroke="#0b7ea8"/><text x="720" y="350" text-anchor="middle" font-size="12" fill="#0b7ea8" font-family="Segoe UI,Arial,sans-serif">Save paper profile</text>
     <text x="508" y="400" font-size="12" fill="#059669" font-family="Segoe UI,Arial,sans-serif">Ready for paper AUTO on Market / Coach</text>`,
  ),
  "analytics.svg": frame(
    "Analytics",
    "Analytics",
    card(24, 140, 210, 90, "Expectancy", "+0.18R") +
      card(250, 140, 210, 90, "Profit factor", "1.42") +
      card(476, 140, 210, 90, "Max DD", "12.4%") +
      card(702, 140, 210, 90, "Discipline", "Good") +
      `<rect x="24" y="250" width="448" height="220" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="40" y="280" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">By asset</text>
     <text x="40" y="320" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">BTC · WR 61% · PF 1.6</text>
     <text x="40" y="350" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">ETH · WR 48% · PF 1.1</text>
     <text x="40" y="380" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">SOL · WR 52% · PF 1.3</text>
     <rect x="488" y="250" width="448" height="220" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="504" y="280" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">By emotion (Journal)</text>
     <text x="504" y="320" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">calm · best expectancy</text>
     <text x="504" y="350" font-size="13" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">impatient · more stop-outs</text>
     <text x="504" y="400" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Combines History fills + Journal tags</text>`,
  ),
  "settings.svg": frame(
    "Settings",
    "Settings",
    `<text x="24" y="148" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Risk rules, coach AUTO defaults, and paper account controls.</text>
     <rect x="24" y="170" width="448" height="290" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="44" y="202" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Coach auto</text>
     <text x="44" y="228" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Entry rules come from Lab · risk lives here</text>
     <text x="44" y="268" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Interval 15m · Tick 20s · Stake $100 · Lev 3x</text>
     <text x="44" y="298" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">SL 1.2% · TP 2.4% · min net R:R</text>
     <rect x="44" y="330" width="160" height="36" rx="8" fill="#0b7ea8"/><text x="124" y="353" text-anchor="middle" font-size="13" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Save coach auto</text>
     <rect x="488" y="170" width="448" height="290" rx="12" fill="#fff" stroke="#dbe3ee"/>
     <text x="508" y="202" font-size="14" font-weight="600" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Risk &amp; account</text>
     <text x="508" y="240" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Starting balance $20,000</text>
     <text x="508" y="270" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Max risk / trade · daily loss · trades/day</text>
     <text x="508" y="300" font-size="13" fill="#334155" font-family="Segoe UI,Arial,sans-serif">Require stop loss · trading enabled</text>
     <text x="508" y="350" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Reset paper account when you need a clean slate</text>
     <text x="508" y="400" font-size="12" fill="#0b7ea8" font-family="Segoe UI,Arial,sans-serif">Open User Guide → /guide</text>`,
  ),
  "lab-auto-flow.svg": `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="320" viewBox="0 0 960 320">
  <defs><linearGradient id="bg2" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#e8f6fc"/><stop offset="100%" stop-color="#f8fafc"/></linearGradient></defs>
  <rect width="960" height="320" rx="16" fill="url(#bg2)" stroke="#dbe3ee"/>
  <text x="32" y="42" font-size="18" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">Lab → AUTO loop</text>
  <text x="32" y="68" font-size="13" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">Built-in A4/CCR entry strategies are removed. Paper signals use Lab profiles only.</text>
  ${[
    ["1", "Prompt", "Lab"],
    ["2", "Backtest", "Lab"],
    ["3", "Promote", "Lab"],
    ["4", "AUTO", "Market / Coach"],
    ["5", "Review", "Portfolio · History · Journal"],
  ]
    .map((s, i) => {
      const x = 32 + i * 186;
      return `<rect x="${x}" y="110" width="168" height="140" rx="12" fill="#fff" stroke="#0b7ea8"/>
    <circle cx="${x + 28}" cy="142" r="16" fill="#0b7ea8"/><text x="${x + 28}" y="147" text-anchor="middle" font-size="13" fill="#fff" font-family="Segoe UI,Arial,sans-serif">${s[0]}</text>
    <text x="${x + 20}" y="186" font-size="16" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">${s[1]}</text>
    <text x="${x + 20}" y="212" font-size="12" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">${s[2]}</text>`;
    })
    .join("")}
</svg>`,
};

for (const [name, content] of Object.entries(files)) {
  fs.writeFileSync(path.join(outDir, name), content);
  console.log("wrote", name);
}
