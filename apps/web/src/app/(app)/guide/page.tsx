import Link from "next/link";
import { HelpCircle } from "lucide-react";

import { PaperBanner } from "@/components/layout/paper-banner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type GuideSection = {
  id: string;
  title: string;
  image: string;
  purpose: string;
  actions: string[];
  connects: string;
};

const SECTIONS: GuideSection[] = [
  {
    id: "dashboard",
    title: "Dashboard",
    image: "/guide/dashboard.svg",
    purpose:
      "Your home overview: portfolio value, cash, P&L, win rate, equity path, and open positions.",
    actions: [
      "Scan daily P&L and trades today before opening new risk.",
      "Review open positions, then jump to Market for charts or AUTO.",
    ],
    connects: "Summarizes Portfolio and History. Use it as a health check before Lab or Desk work.",
  },
  {
    id: "market",
    title: "Market",
    image: "/guide/market.svg",
    purpose:
      "Charts plus Lab paper AUTO for any listed symbol. EMA lines follow chart_emas from your selected promoted Lab profile.",
    actions: [
      "Select a symbol that matches your Lab profile (catalog includes BTC, ETH, SOL, and many others).",
      "Choose a promoted Lab profile in the AUTO card, then turn AUTO on — leave the tab open for ticks.",
      "Use Manual ticket for a classic order ticket on that symbol.",
    ],
    connects:
      "AUTO entries come only from Lab profiles. Fills appear in Portfolio and History; risk defaults live in Settings.",
  },
  {
    id: "desk",
    title: "Desk",
    image: "/guide/desk.svg",
    purpose: "A simple Buy / Sell paper desk for manual practice. Fills are always simulated.",
    actions: [
      "Pick a coin, size a notional, and Buy or Sell.",
      "Watch the position snapshot update after each fill.",
    ],
    connects:
      "Independent of Lab AUTO. Manual fills still feed Portfolio, History, Journal, and Analytics.",
  },
  {
    id: "portfolio",
    title: "Portfolio",
    image: "/guide/portfolio.svg",
    purpose: "Live holdings, allocation, and unrealized P&L across open paper positions.",
    actions: [
      "Check quantity, entry, mark, and allocation per symbol.",
      "Open a symbol’s trade page when you want to manage size manually.",
    ],
    connects: "Updated by Desk buys/sells and Lab AUTO fills from Market or Coach.",
  },
  {
    id: "history",
    title: "History",
    image: "/guide/history.svg",
    purpose: "Complete list of paper fills with filters for symbol, side, P&L, and date.",
    actions: [
      "Filter closed winners/losers when reviewing a session.",
      "Confirm fees and realized P&L after AUTO or Desk exits.",
    ],
    connects: "Source of truth for Analytics metrics and for Journal write-ups after the fact.",
  },
  {
    id: "journal",
    title: "Journal",
    image: "/guide/journal.svg",
    purpose: "Capture setup notes and emotions so you learn why a trade felt right or wrong.",
    actions: [
      "Log symbol, setup name, notes, and an emotion tag after important trades.",
      "Re-read recent notes before changing Lab rules.",
    ],
    connects: "Emotion tags power Analytics “by emotion.” Pair with History for honest review.",
  },
  {
    id: "coach",
    title: "Coach",
    image: "/guide/coach.svg",
    purpose:
      "Practice stats plus the same Lab paper AUTO desk as Market. Entries come from your Lab prompts.",
    actions: [
      "Track practice progress toward 200–500 paper trades.",
      "Select a promoted Lab profile and keep the page open so AUTO can tick (browser interval — not server 24/7).",
      "Tune stake, interval, SL/TP defaults in Settings (saved to your account).",
    ],
    connects:
      "Same AUTO engine as Market. Profiles are created in Lab; outcomes show in Portfolio, History, and Analytics.",
  },
  {
    id: "lab",
    title: "Lab",
    image: "/guide/lab.svg",
    purpose:
      "Hypothesis Lab: describe rules in plain English, generate an immutable version, backtest with fees, then save a paper profile. Hypotheses are private to your account. Optional Trade-to-Live template favors WAIT/NO TRADE unless trend, zone confirmation, and RR ≥ 1:2 are present.",
    actions: [
      "Write a prompt (symbol, interval, entries, filters, stop/target). Or click Use Trade-to-Live template for a single high-quality long setup.",
      "Generate a testable version, then Backtest (≈0.80% fee per fill). REJECT is common and expected.",
      "Save paper profile (promote) when you want AUTO to use it. Paper testing is free for now; Pro billing coming later.",
    ],
    connects:
      "Only promoted Lab profiles drive Market/Coach paper AUTO. Other users cannot see your Lab work. Assistant rules prefer quality over forced entries.",
  },
  {
    id: "assistant",
    title: "Trading Analysis Assistant",
    image: "/guide/lab-auto-flow.svg",
    purpose:
      "Paper-practice checklist used by Lab/AUTO: select high-quality setups only. Incomplete conditions mean WAIT or NO TRADE — never invent a signal just to trade.",
    actions: [
      "Step 1 Trend: up / down / unclear (WAIT if unclear).",
      "Step 2 S/R as zones — never enter on touch alone.",
      "Step 3 Lower-timeframe closed-bar confirmation before entry.",
      "Step 4 Risk:Reward at least 1:2 with structure-valid stop and target.",
      "Step 5 Final: BUY/LONG, SELL/SHORT, WAIT, or NO TRADE with reasons.",
    ],
    connects:
      "Practice goals only (~1–3 quality paper setups/week). Not income promises, not live brokerage. Wire through Lab → Save paper profile → Market/Coach AUTO.",
  },
  {
    id: "analytics",
    title: "Analytics",
    image: "/guide/analytics.svg",
    purpose: "Expectancy, profit factor, drawdown, discipline, and breakdowns by asset and emotion.",
    actions: [
      "Compare assets before concentrating AUTO risk.",
      "Check emotion stats after you have Journal coverage.",
    ],
    connects: "Built from History fills and Journal tags. Use it to decide which Lab profiles deserve more paper size.",
  },
  {
    id: "settings",
    title: "Settings",
    image: "/guide/settings.svg",
    purpose:
      "Account risk limits, coach AUTO defaults (interval, stake, leverage, SL/TP), paper reset, and a link to this guide. New accounts start at $20,000 simulated cash.",
    actions: [
      "Set candle interval, AUTO tick seconds, stake, and leverage for Lab AUTO (stored per account on the server).",
      "Configure max risk per trade, daily loss, and trades/day.",
      "Reset the paper account when you want a clean practice slate.",
    ],
    connects:
      "Risk defaults apply to Market/Coach AUTO. Entry logic still comes from Lab profiles, not Settings.",
  },
];

export default function GuidePage() {
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mb-1 inline-flex items-center gap-2 text-sm font-medium text-primary">
            <HelpCircle className="h-4 w-4" />
            User Guide
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">How Paper Crypto Coach works</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Concise walkthrough of every tab. Simulated money only — nothing here trades real funds.
            New paper accounts start with $20,000.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/lab">Start in Lab</Link>
        </Button>
      </div>

      <PaperBanner />

      <Alert>
        <AlertTitle>Lab-first paper AUTO</AlertTitle>
        <AlertDescription>
          Paper signals and AUTO use Hypothesis Lab profiles only. Prompt → backtest → Save paper
          profile → turn AUTO on in Market or Coach and leave the tab open. Prefer WAIT / NO
          TRADE when a setup is incomplete — quality over forced entries (see Trading Analysis Assistant).
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Lab → AUTO loop</CardTitle>
          <CardDescription>
            One path for automated paper entries. Keep Market or Coach open while AUTO ticks in the
            browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <img
            src="/guide/lab-auto-flow.svg"
            alt="Lab to AUTO flow: prompt, backtest, promote, AUTO, review"
            className="w-full rounded-lg border bg-muted/20"
          />
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
            <li>
              <Link href="/lab" className="font-medium text-foreground underline-offset-4 hover:underline">
                Lab
              </Link>
              : describe rules, generate a version, backtest, Save paper profile.
            </li>
            <li>
              <Link href="/settings" className="font-medium text-foreground underline-offset-4 hover:underline">
                Settings
              </Link>
              : set interval, stake, leverage, SL/TP for AUTO risk (saved to your account).
            </li>
            <li>
              <Link href="/market" className="font-medium text-foreground underline-offset-4 hover:underline">
                Market
              </Link>{" "}
              or{" "}
              <Link href="/coach" className="font-medium text-foreground underline-offset-4 hover:underline">
                Coach
              </Link>
              : choose the promoted profile, turn AUTO on, leave the page open.
            </li>
            <li>
              Review fills in Portfolio / History, then Journal and Analytics.
            </li>
          </ol>
        </CardContent>
      </Card>

      <nav aria-label="Guide sections" className="flex flex-wrap gap-2">
        {SECTIONS.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="rounded-md border bg-background px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {section.title}
          </a>
        ))}
      </nav>

      <div className="space-y-10">
        {SECTIONS.map((section) => (
          <section key={section.id} id={section.id} className="scroll-mt-28 space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xl font-semibold tracking-tight">{section.title}</h2>
              <Button asChild size="sm" variant="secondary">
                <Link href={`/${section.id}`}>Open {section.title}</Link>
              </Button>
            </div>
            <img
              src={section.image}
              alt={`${section.title} tab overview`}
              className="w-full rounded-lg border bg-muted/20 shadow-sm"
            />
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">What it is for</CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">{section.purpose}</CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Key actions</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="list-disc space-y-1.5 pl-4 text-sm text-muted-foreground">
                    {section.actions.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">How it connects</CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">{section.connects}</CardContent>
              </Card>
            </div>
          </section>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tips</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Paper trading only — never real funds. Sign in with email/password or Google (when enabled).</p>
          <p>
            Lab hypotheses and Coach AUTO prefs are per account on the server — not shared with other
            users.
          </p>
          <p>
            Free: unlimited Lab backtests and Save paper profile for paper testing. Pro billing
            coming later (optional; not required for AUTO).
          </p>
          <p>
            AUTO evaluates closed candles and fills eligible longs at the next candle open. Leave
            Market or Coach open — ticks pause if you close the tab (not a 24/7 server job).
          </p>
          <p>
            Backtests include ≈0.80% fee per fill; REJECT is a normal research outcome. EMAs from your
            Lab prompt draw on the Market chart when that profile is selected.
          </p>
          <p>English-only UI.</p>
        </CardContent>
      </Card>
    </div>
  );
}
