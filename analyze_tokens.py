import json
import pandas as pd

def analyze():
    tokens = {}

    # Load token data from JSONL
    try:
        with open("token_data.jsonl", "r") as f:
            for line in f:
                event = json.loads(line)
                data = event["data"]
                mint = data["mint"]

                if event["event_type"] == "new_token":
                    tokens[mint] = {
                        "symbol": data["symbol"],
                        "dev_stake_pct": data.get("dev_stake_pct", 0),
                        "ticker_score": data.get("ticker_score", 0),
                        "has_website": data["has_website"],
                        "has_twitter": data["has_twitter"],
                        "initial_price": data["initial_price"],
                        "max_gain": 0.0,
                        "max_velocity": 0.0
                    }
                elif event["event_type"] == "performance_alert":
                    if mint in tokens:
                        tokens[mint]["max_gain"] = max(tokens[mint]["max_gain"], data["gain"])
                        tokens[mint]["max_velocity"] = max(tokens[mint]["max_velocity"], data.get("velocity", 0))
    except FileNotFoundError:
        print("token_data.jsonl not found.")
        return

    df = pd.DataFrame.from_dict(tokens, orient='index')
    if df.empty:
        print("No tokens found in log.")
        return

    print("--- Enhanced Token Analysis Summary ---")
    print(f"Total tokens scanned: {len(df)}")

    high_performers = df[df['max_gain'] >= 100]
    print(f"Tokens with 100%+ gain: {len(high_performers)}")

    print("\n--- Developer Holding Analysis ---")
    print(f"Avg Dev Stake (All): {df['dev_stake_pct'].mean():.2f}%")
    print(f"Avg Dev Stake (High Performers): {high_performers['dev_stake_pct'].mean():.2f}%")

    print("\n--- Ticker Score Analysis ---")
    print(f"Avg Ticker Score (All): {df['ticker_score'].mean():.2f}")
    print(f"Avg Ticker Score (High Performers): {high_performers['ticker_score'].mean():.2f}")

    print("\n--- Price Velocity Analysis ---")
    high_velocity_tokens = df[df['max_velocity'] > 0.005]
    print(f"Tokens with high velocity (>0.5%/s): {len(high_velocity_tokens)}")
    success_in_high_velocity = high_velocity_tokens[high_velocity_tokens['max_gain'] >= 100]
    velocity_success_rate = (len(success_in_high_velocity) / len(high_velocity_tokens) * 100) if len(high_velocity_tokens) > 0 else 0
    print(f"Success rate among high velocity tokens: {velocity_success_rate:.2f}%")

    print("\n--- Top Performers Details ---")
    print(high_performers[['symbol', 'max_gain', 'dev_stake_pct', 'ticker_score', 'max_velocity']].sort_values(by='max_gain', ascending=False))

if __name__ == "__main__":
    analyze()
