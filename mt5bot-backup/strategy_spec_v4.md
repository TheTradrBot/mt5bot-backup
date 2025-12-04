# Blueprint HTF Confluence Strategy – Spec (v4 – The5ers 10K High Stakes)

> **File name suggestion:** `Strategy_spec_V4_The5ers10K.md`  
> This version keeps the HTF framework from v4 but **optimizes risk & execution**  
> to pass **The5ers 10K High Stakes challenge (Step 1 & funded stages)**.

---

## 0. The5ers 10K High Stakes constraints

Designed specifically for **The5ers High Stakes 10K account**:

- **Account size:** $10,000  
- **Program:** High Stakes (2-step evaluation + funded stages) :contentReference[oaicite:0]{index=0}  
- **Targets:**
  - Step 1: **+8%**  
  - Step 2: **+5%**
- **Drawdown rules (all steps & funded):** :contentReference[oaicite:1]{index=1}  
  - **Max daily loss:** 5% of previous day’s **balance/equity snapshot** (whichever is higher)  
  - **Max overall loss (absolute):** 10% of **initial balance** (never go below $9,000 on a 10K)  
- **Min profitable days:** 3 in each evaluation step :contentReference[oaicite:2]{index=2}  
- **Leverage:** up to 1:100 (MT5) :contentReference[oaicite:3]{index=3}  
- **No time limit**, but account expires after **30 days of no trading activity**. :contentReference[oaicite:4]{index=4}  
- **News restriction (High Stakes):** no order execution within **2 minutes before and after** high-impact news on the instrument’s symbol; open trades may remain running. :contentReference[oaicite:5]{index=5}  

This spec:

- **Hard-codes** the 10K account size as default for risk calculation.
- Ensures **worst-case open risk can’t breach the 5% daily loss** or 10% absolute loss.
- Uses **no new trades on Fridays** (but existing trades may stay open) as an extra safety rule.

---

## 1. High-level overview

### 1.1 Style & holding period

- **Swing / position** trading on HTFs:
  - **Daily** = framework & setup chart (always)
  - **4H** = execution / entry chart
  - **Weekly & Monthly** = macro context
- Average holding time: **several days up to ~1–2 weeks**.
- New trades are **never opened on Fridays** (broker server time):
  - Existing trades can remain open with SL/TP.
  - No scaling in or new entries on Fridays.

---

### 1.2 Markets

Applies to:

- **FX majors & key minors** (e.g. EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD)
- **Gold & Silver** (XAUUSD, XAGUSD)
- **Indices** (SPX500, NAS100, US30 etc.) – if margin fits within 1:100 leverage
- **Crypto majors** (BTCUSD, ETHUSD) – only if spreads/conditions are acceptable

Requirements:

- Clean HTF structure, respect for S/R.
- Sufficient history for backtests.

---

### 1.3 Core components

- **S/R zones** (MN, W1, D1)
- **Market structure** (HH/HL, LH/LL, BOS, CHOCH)
- **Daily Fibonacci** (body → wick) on **specific impulses**:
  - Bullish N / Bearish V → leg-1 impulse
  - Inverse H&S / H&S → neckline-break impulse
- **Daily supply/demand (OBs)** as refined entry zones
- **Liquidity** (equal highs/lows, prior highs/lows) as **confluence**, not requirement
- **4H entry logic**:
  - Entry is based only on **4H closes inside a Daily entry zone**  
    (no 4H BOS/CHOCH or liquidity pattern filters).

---

## 2. Timeframes & bias

### 2.1 Stack

- **Monthly (MN)** – macro S/R & trend context.
- **Weekly (W1)** – primary directional bias.
- **Daily (D1)** – always the **framework & setup** TF.
- **4H (H4)** – only for **entry timing** and candle-close conditions.

### 2.2 Weekly bias

- Weekly HH/HL + last BOS **up** → bullish bias.
- Weekly LH/LL + last BOS **down** → bearish bias.
- Choppy around large MN S/R → neutral.

### 2.3 Daily within Weekly

- In a Weekly **uptrend**:
  - Buy pullbacks from Daily demand within fib **0.618–0.796**.
- In a Weekly **downtrend**:
  - Sell rallies from Daily supply within fib **0.618–0.796**.
- In Weekly neutral:
  - Focus on **reversal frameworks** at MN/W1 levels (H&S / inverse H&S).

---

## 3. Support & Resistance (S/R)

- Always drawn as **zones**, not single lines.
- **MN**: long-term turning points.  
- **W1**: major swings inside MN.  
- **D1**: local structure aligning with OBs and fib zones.

S/R filters:

- Trade frameworks only if they align with MN/W1 zones.
- Use S/R for both **entry zone context** and **TP targets**.

---

## 4. Market structure

### 4.1 Basics

- Uptrend: HH + HL, protected HLs.
- Downtrend: LH + LL, protected LHs.
- **BOS**: decisive close beyond prior swing (breakaway candle).
- **CHOCH**: first valid BOS against current trend.

### 4.2 Daily structure

Daily structure drives:

- Impulse selection for fibs.
- Whether we trade continuation (N/V) or reversal (H&S / inverse H&S).

### 4.3 4H structure – limited use

- 4H structure is **informational only**.
- **The bot must not use 4H BOS/CHOCH** as an entry or filter.

---

## 5. Supply & demand (Daily OBs)

### 5.1 Demand (longs)

- Last bearish candle/cluster before a strong bullish impulse that **breaks structure up**.
- Zone: open of last bearish candle → lowest wick of that base.

### 5.2 Supply (shorts)

- Last bullish candle/cluster before strong bearish impulse that **breaks structure down**.
- Zone: open of last bullish candle → highest wick.

### 5.3 Valid OB requirements

- Impulsive move away (large candles, low overlap).
- Causes a Daily BOS or clears significant liquidity.
- Sits near MN/W1 S/R and inside relevant fib retracement.

### 5.4 Freshness

- Prefer **fresh** or **first retest** of OB.
- Each additional touch reduces edge.

---

## 6. Structural frameworks (Daily only)

### 6.1 Inverse H&S – bullish reversal

- After downtrend at MN/W1 support.
- Left shoulder → deeper head → higher right shoulder.
- Daily BOS **up** through neckline confirms.

**Impulse for fib:**  
Daily **neckline-break impulse up** (body → wick).

### 6.2 H&S – bearish reversal

- After uptrend at MN/W1 resistance.
- Left shoulder → higher head → lower right shoulder.
- Daily BOS **down** through neckline confirms.

**Impulse for fib:**  
Daily **neckline-break impulse down** (body → wick).

### 6.3 Bullish N – continuation

- Leg-1: strong Daily impulse up with BOS.
- Leg-2: corrective pullback.
- Leg-3: expected continuation upward.

**Impulse for fib:**  
Daily **leg-1 up** (body low → wick high).

### 6.4 Bearish V – continuation

- Leg-1: strong Daily impulse down with BOS.
- Leg-2: corrective rally.
- Leg-3: expected continuation down.

**Impulse for fib:**  
Daily **leg-1 down** (body high → wick low).

### 6.5 Framework + confluence

Only trade frameworks when:

- At/near MN/W1 S/R.  
- The **leg-2 / shoulder** terminates in:
  - Daily OB and
  - Fib **0.618–0.796** zone of the correct impulse.

---

## 7. Fibonacci rules (Daily, body → wick)

### 7.1 Anchor selection

- **Up impulse:** body cluster at low → highest wick at high.
- **Down impulse:** body cluster at high → lowest wick at low.
- Only on meaningful Daily swings:
  - Leg-1 of N/V, or
  - Neckline-break impulse of H&S / inverse H&S.

### 7.2 Levels

- **Retracements**:
  - 0.50 (context)
  - **0.618**
  - **0.66**
  - **0.796** (deep)
- **Extensions** (for TPs):
  - −0.25, −0.68, −1.00, −1.42, −2.00  
  - (−2.618, −3.0 optional for strong trends)

### 7.3 Daily entry zone

Daily entry zone = intersection of:

1. Correct Daily impulse’s fib band **0.618–0.796**  
2. **Daily OB** (demand or supply)  
3. Ideally MN/W1 S/R

This zone is then projected to 4H for execution.

---

## 8. Liquidity & magnetic levels

- Mark on MN/W1/D1:
  - Equal highs/lows
  - Prior month/week/day highs & lows
  - Major swing extremes
- **External liquidity:** outside current main swing range (bigger reversals).  
- **Internal liquidity:** within range (continuations).

Used as **extra confluence** only; **never mandatory** to have a sweep.

---

## 9. Liquidity flows

- Price tends to move:
  - From one liquidity pool to the next,
  - Following BOS & impulses.
- After BOS + displacement:
  - Expect pullback to origin OB + fib zone,
  - Then continuation towards next significant liquidity pool (prior highs/lows, fib extensions).

Helps with:

- Deciding which fib extension to target.
- Knowing when to hold vs take partials.

---

## 10. HTF bias workflow

1. **Monthly**
   - Mark MN S/R, major highs/lows, external liquidity.
   - Note macro trend & where price sits inside the macro range.

2. **Weekly**
   - Determine HH/HL vs LH/LL and the last BOS direction.
   - Mark Weekly OBs and swings inside MN zones.
   - Set `weekly_bias` = bullish / bearish / neutral.

3. **Daily**
   - Align with Weekly:
     - Continuations: N/V with trend.
     - Reversals: H&S / inverse H&S at MN/W1 levels.
   - Choose correct Daily impulse and fib anchors.
   - Build Daily entry zones from OB + fib band.

Only when HTF context + Daily framework + entry zone align do we allow 4H execution logic to run.

---

## 11. 4H execution logic – v4 rule

### 11.1 Role of 4H

- 4H is **only** used to decide **when** to enter, never **where**.
- No 4H frameworks, no 4H BOS/CHOCH filters are used in the algorithm.

### 11.2 3-candle close rule

For both longs and shorts:

1. Wait until price **enters the Daily entry zone** (projected on 4H).
2. Start counting **4H candles** whose **closes** lie inside that zone.
3. When there are **3 consecutive 4H closes inside the zone**:
   - **Entry price = close of the 3rd 4H candle.**
4. Direction:
   - Long: Daily demand + fib band of bullish impulse.
   - Short: Daily supply + fib band of bearish impulse.

Wicks may go in/out of the zone; only the **close** must be inside.

---

## 12. Entry checklists

### 12.1 Longs (The5ers-safe)

1. `weekly_bias` bullish, or MN support + clear Daily bullish framework.
2. Daily impulse defined (leg-1 up, or neckline-break up).
3. Fib (body → wick) drawn on that impulse.
4. Daily **demand** overlaps fib 0.618–0.796 + HTF support ⇒ **Daily entry zone**.
5. 4H prints **3 consecutive closes inside the zone** ⇒ **enter long at 3rd close**.
6. SL:
   - Below low of Daily demand zone **and** leg-2/head/right-shoulder low (whichever is lower).
7. TPs:
   - TP1: prior swing high or −0.25 extension.
   - TP2: −0.68.
   - TP3: −1.00.
   - Optional: −1.42, −2.00 in strong trend.
8. R:R:
   - TP1 must offer **≥ 2R**.

### 12.2 Shorts (The5ers-safe)

Mirror:

1. `weekly_bias` bearish, or MN resistance + Daily bearish framework.
2. Daily impulse defined (leg-1 down, or neckline-break down).
3. Fib drawn body → wick.
4. Daily **supply** overlaps fib 0.618–0.796 + HTF resistance ⇒ entry zone.
5. 4H prints 3 closes inside zone ⇒ **enter short at 3rd close**.
6. SL above high of Daily supply & relevant swing high.
7. TPs via prior low and fib −0.25 / −0.68 / −1.00 / −1.42 / −2.00.
8. TP1 ≥ 2R.

---

## 13. Risk & money management (The5ers 10K tuned)

### 13.1 Hard constraints from The5ers (for 10K account)

- **Initial balance:** 10,000.
- **Max overall loss (10%):** equity must **never** go below **9,000**.
- **Max daily loss (5%):** on each day `D`, snapshot reference is  
  `ref_D = max(balance_{D-1}, equity_{D-1})`.  
  Daily account stopout if `equity_D < ref_D - 0.05 * ref_D`. :contentReference[oaicite:6]{index=6}  

### 13.2 Internal risk limits (safety margins)

To avoid accidental breaches:

- **Base per-trade risk:**  
  `risk_per_trade = 0.75% of current equity` (0.0075).

- **Max open risk at any moment:**  
  `max_open_risk_total = 3.0%` of equity  
  → e.g. four trades at 0.75% each = 3.0%.

- **Max daily risk used for new trades:**  
  `internal_daily_loss_cap = 4.0%` of `ref_D`.  
  (Official limit is 5%; we keep **1% buffer**.)

- **Max overall drawdown for new entries:**  
  Stop opening new trades if total drawdown from initial balance reaches **8%**.  
  (Leaves 2% buffer vs the 10% absolute loss.)

**Worst-case:**  
If all open trades hit SL the same day, total loss ≤ 3% (plus slippage),  
comfortably inside the 5% daily limit.

### 13.3 Daily risk accounting logic

At start of each trading day `D`:

1. Compute `ref_D = max(balance_{D-1}, equity_{D-1})`.  
2. Official daily limit: `official_daily_limit = 0.05 * ref_D`.  
3. Internal allowed loss: `internal_daily_limit = 0.04 * ref_D`.

During the day:

- Track `realized_loss_today` in % of `ref_D`.
- Track `open_risk_today` = sum of % risk from entry to SL for all open trades initiated on or before day D.

Before opening a new trade with risk `%r_new`:

```text
if (realized_loss_today + open_risk_today + r_new) > internal_daily_limit
    → skip this entry (no trade)
