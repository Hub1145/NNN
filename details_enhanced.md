# Enhanced Pump.fun Sniper Signals - Findings Report

This report analyzes the performance of newly launched tokens using advanced signals including developer holdings, price velocity, and ticker scoring.

## Methodology
- **Developer Holding**: Tracked the percentage of supply the developer purchased at launch (`initialBuy`).
- **Price Velocity**: Calculated the rate of price change per second. A threshold of >0.5%/s was used to identify "high velocity" tokens.
- **Ticker Score**: Scored tokens based on "evergreen" meme keywords (1pt) and currently trending words from DexScreener (3pts).
- **Performance Criteria**: 100%+ price gain from launch.

## Executive Summary
- **Total Tokens Scanned**: 233 (cumulative from previous runs)
- **High Performers (100%+ gain)**: 14 total.
- **Velocity Success Rate**: 28.57% of tokens hitting high velocity reached 100%+ gain within 1 hour.

## Key Insights

### 1. Developer Holding Percentage
Tokens where the developer held a smaller initial stake (below 2%) tended to perform better in this sample.
- **Avg Dev Stake (All)**: 3.36%
- **Avg Dev Stake (High Performers)**: **1.37%**
- **Analysis**: High developer concentration (5%+) might be perceived as a rug risk, leading to lower buying pressure from the community.

### 2. Ticker Scoring (NLP)
High performers had significantly higher ticker scores, indicating strong alignment with meme "meta" and trending topics.
- **Avg Ticker Score (All)**: 1.12
- **Avg Ticker Score (High Performers)**: **3.00**
- **Analysis**: Cultural resonance (e.g., `BABYHOUSE`, `hentai`) remains the strongest non-onchain predictor of a pump.

### 3. Price Velocity as a Trigger
Velocity is a powerful lead indicator.
- **Threshold**: >0.005 (0.5% gain per second).
- **Result**: Tokens hitting this velocity had a **28.57%** chance of hitting a 100% gain, compared to the baseline 5.1% success rate.
- **Recommendation**: Sniper bots should use velocity spikes in the first 30-60 seconds as a primary "Buy" signal.

## Top Performers (Enhanced Run)
| Symbol | Max Gain | Dev Stake % | Ticker Score | Max Velocity |
|--------|----------|-------------|--------------|--------------|
| BABYHOUSE| 348% | 1.8% | 3 | 0.086/s |
| hentai | 242% | 0.9% | 3 | 0.093/s |

## Sniper Bot Strategy Recommendations
1. **Developer Filter**: Filter for tokens where `dev_stake_pct < 3%`.
2. **Velocity Trigger**: Execute snipe when `velocity > 0.005/s` and `ticker_score >= 1`.
3. **Sentiment Boost**: Use trending words from DexScreener to dynamically weight tickers.
4. **Unique Buyers**: (Future Implementation) Integrate unique buyer counts from the trade stream to confirm organic interest.
