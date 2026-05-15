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
                        "has_website": data["has_website"],
                        "has_twitter": data["has_twitter"],
                        "has_telegram": data["has_telegram"],
                        "initial_price": data["initial_price"],
                        "max_gain": 0.0,
                        "v_sol": data.get("v_sol", 0)
                    }
                elif event["event_type"] == "high_gain":
                    if mint in tokens:
                        tokens[mint]["max_gain"] = max(tokens[mint]["max_gain"], data["gain"])
    except FileNotFoundError:
        print("token_data.jsonl not found.")
        return

    df = pd.DataFrame.from_dict(tokens, orient='index')

    if df.empty:
        print("No tokens found in log.")
        return

    print("--- Token Analysis Summary ---")
    print(f"Total tokens scanned: {len(df)}")

    high_performers = df[df['max_gain'] >= 100]
    print(f"Tokens with 100%+ gain: {len(high_performers)}")

    print("\n--- Correlation Analysis ---")

    metrics = ['has_website', 'has_twitter', 'has_telegram']
    for metric in metrics:
        total_with_metric = df[df[metric]].shape[0]
        high_with_metric = high_performers[high_performers[metric]].shape[0]

        rate = (high_with_metric / total_with_metric * 100) if total_with_metric > 0 else 0
        print(f"{metric}: {total_with_metric} tokens total, {high_with_metric} were high performers ({rate:.2f}% success rate)")

    # Analyze without socials
    no_socials = df[~(df['has_website'] | df['has_twitter'] | df['has_telegram'])]
    high_no_socials = high_performers[~(high_performers['has_website'] | high_performers['has_twitter'] | high_performers['has_telegram'])]
    rate_no_socials = (len(high_no_socials) / len(no_socials) * 100) if len(no_socials) > 0 else 0
    print(f"No Socials: {len(no_socials)} tokens total, {len(high_no_socials)} were high performers ({rate_no_socials:.2f}% success rate)")

    print("\n--- Liquidity Analysis ---")
    # v_sol is usually around 30 for pump.fun tokens
    print(f"Average v_sol for all: {df['v_sol'].mean():.2f}")
    print(f"Average v_sol for high performers: {high_performers['v_sol'].mean():.2f}")

    print("\n--- Top Performers ---")
    print(high_performers[['symbol', 'max_gain', 'has_website', 'has_twitter', 'has_telegram']].sort_values(by='max_gain', ascending=False))

if __name__ == "__main__":
    analyze()
