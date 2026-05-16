import asyncio
import json
import websockets
import httpx
import time
import logging
from datetime import datetime
import os
import base64
import struct
import re
from collections import deque, Counter
from pytrends.request import TrendReq

# Configuration
PUMP_WS_URL = os.getenv("PUMP_WS_URL", "wss://pumpportal.fun/api/data")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
if not HELIUS_API_KEY:
    logger.error("HELIUS_API_KEY not found in environment variables.")
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
LOG_FILE = os.getenv("PUMP_LOG_FILE", "token_data.jsonl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EVERGREEN_BOOSTERS = {
    "pepe", "doge", "shib", "wojak", "chad", "based", "giga",
    "moon", "100x", "1000x", "wen", "ser",
    "trump", "elon", "musk", "grok",
    "cat", "dog", "frog", "panda", "bear", "bull", "ape",
    "fire", "god", "king", "sigma", "alpha",
}

class PumpScanner:
    def __init__(self):
        self.watchlist = {} # mint -> token_data
        self.http_client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "pump-scanner/1.0"})
        self.trending_words = set()
        self.dev_history = {} # traderPublicKey -> list of launched mints
        try:
            self.pytrends = TrendReq(hl='en-US', tz=0)
        except:
            self.pytrends = None

    async def fetch_trending_dex(self):
        """Fetch trending tokens from DexScreener to extract keywords."""
        try:
            response = await self.http_client.get("https://api.dexscreener.com/token-boosts/top/v1")
            if response.status_code == 200:
                data = response.json()
                new_words = set()
                for item in data:
                    desc = item.get("description", "").lower()
                    words = re.findall(r'\w+', desc)
                    new_words.update([w for w in words if len(w) > 3])
                return new_words
        except Exception as e:
            logger.error(f"Error fetching trending from DexScreener: {e}")
        return set()

    async def fetch_trending_coingecko(self):
        try:
            response = await self.http_client.get("https://api.coingecko.com/api/v3/search/trending")
            if response.status_code == 200:
                data = response.json()
                new_words = set()
                for coin in data.get("coins", []):
                    name = coin["item"]["name"].lower()
                    symbol = coin["item"]["symbol"].lower()
                    new_words.update(re.findall(r'\w+', name + " " + symbol))
                return new_words
        except Exception as e:
            logger.error(f"Error fetching trending from CoinGecko: {e}")
        return set()

    async def fetch_trending_reddit(self):
        subreddits = ["solana", "memecoins", "cryptocurrency"]
        all_words = []
        try:
            for sub in subreddits:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                response = await self.http_client.get(url)
                if response.status_code == 200:
                    posts = response.json()["data"]["children"]
                    for post in posts:
                        title = post["data"]["title"].lower()
                        all_words.extend(re.findall(r'\b[a-z]{3,12}\b', title))

            stopwords = {"the", "and", "for", "with", "this", "that", "are", "not", "solana", "pump", "crypto"}
            counts = Counter(w for w in all_words if w not in stopwords)
            return set(word for word, _ in counts.most_common(30))
        except Exception as e:
            logger.error(f"Error fetching trending from Reddit: {e}")
        return set()

    def fetch_trending_google(self):
        if not self.pytrends: return set()
        try:
            df = self.pytrends.realtime_trending_searches(pn='US')
            if not df.empty:
                titles = df['title'].str.lower().tolist()
                new_words = set()
                for t in titles:
                    new_words.update(re.findall(r'\w+', t))
                return new_words
        except Exception as e:
            logger.debug(f"Google Trends error (likely rate limit): {e}")
        return set()

    async def fetch_metadata(self, uri):
        if not uri:
            return None
        if uri.startswith("ipfs://"):
            uri = uri.replace("ipfs://", "https://ipfs.io/ipfs/")
        try:
            response = await self.http_client.get(uri)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching metadata from {uri}: {e}")
        return None

    def score_ticker(self, name, symbol):
        text = f"{name} {symbol}".lower()
        words = set(re.findall(r'\w+', text))
        evergreen_hits = words & EVERGREEN_BOOSTERS
        trending_hits = words & self.trending_words
        score = len(evergreen_hits) * 1 + len(trending_hits) * 3
        return score, list(evergreen_hits), list(trending_hits)

    async def log_token_event(self, event_type, data):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

    async def process_new_token(self, event):
        mint = event.get("mint")
        name = event.get("name")
        symbol = event.get("symbol")
        uri = event.get("uri")
        trader = event.get("traderPublicKey")
        initial_buy = event.get("initialBuy", 0)
        bonding_curve_key = event.get("bondingCurveKey")
        v_tokens = event.get("vTokensInBondingCurve")
        v_sol = event.get("vSolInBondingCurve")

        logger.info(f"New Token: {name} ({symbol}) - {mint} by {trader}")

        metadata = await self.fetch_metadata(uri)
        has_website = False
        has_twitter = False
        has_telegram = False

        if metadata:
            has_website = bool(metadata.get("website") or "website" in str(metadata).lower())
            has_twitter = bool(metadata.get("twitter") or "twitter" in str(metadata).lower() or "x.com" in str(metadata).lower())
            has_telegram = bool(metadata.get("telegram") or "t.me" in str(metadata).lower())

        initial_price = (v_sol * 1e9) / (v_tokens * 1e6) if v_tokens else 0

        # Dev stake %
        # Total supply is usually 1,000,000,000 tokens
        dev_stake_pct = (initial_buy / 1e9) * 100 # Assuming 1B supply

        ticker_score, evergreen, trending = self.score_ticker(name, symbol)

        token_data = {
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "trader": trader,
            "dev_stake_pct": dev_stake_pct,
            "bonding_curve_key": bonding_curve_key,
            "initial_price": initial_price,
            "current_price": initial_price,
            "max_price": initial_price,
            "price_history": deque(maxlen=20),
            "v_sol": v_sol,
            "v_tokens": v_tokens,
            "has_website": has_website,
            "has_twitter": has_twitter,
            "has_telegram": has_telegram,
            "ticker_score": ticker_score,
            "evergreen_hits": evergreen,
            "trending_hits": trending,
            "created_at": datetime.now().isoformat(),
            "metadata": metadata
        }
        token_data["price_history"].append({"ts": time.time(), "price": initial_price})

        self.watchlist[mint] = token_data
        await self.log_token_event("new_token", {k: v for k, v in token_data.items() if k != "price_history"})

    async def update_prices(self):
        while True:
            await asyncio.sleep(30)
            if not self.watchlist:
                continue

            logger.info(f"Updating prices for {len(self.watchlist)} tokens...")
            mints = list(self.watchlist.keys())
            for i in range(0, len(mints), 100):
                batch = mints[i:i+100]
                keys = [self.watchlist[m]["bonding_curve_key"] for m in batch]

                payload = {
                    "jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                    "params": [keys, {"encoding": "base64"}]
                }

                try:
                    response = await self.http_client.post(HELIUS_RPC_URL, json=payload)
                    if response.status_code == 200:
                        results = response.json().get("result", {}).get("value", [])
                        for j, res in enumerate(results):
                            if res and res.get("data"):
                                raw_data = base64.b64decode(res["data"][0])
                                if len(raw_data) < 24: continue
                                v_tokens, v_sol = struct.unpack("<QQ", raw_data[8:24])

                                mint = batch[j]
                                current_price = v_sol / v_tokens if v_tokens else 0

                                token = self.watchlist[mint]
                                token["current_price"] = current_price
                                if current_price > token["max_price"]:
                                    token["max_price"] = current_price

                                now = time.time()
                                token["price_history"].append({"ts": now, "price": current_price})

                                # Velocity Score (% change per second)
                                velocity = 0.0
                                if len(token["price_history"]) >= 2:
                                    oldest = token["price_history"][0]
                                    dt = now - oldest["ts"]
                                    if dt > 0:
                                        dp = (current_price - oldest["price"]) / oldest["price"]
                                        velocity = dp / dt

                                gain = (current_price / token["initial_price"] - 1) * 100
                                if gain >= 100 or velocity > 0.005:
                                    status = "🚀 HIGH GAIN" if gain >= 100 else "🔥 HIGH VELOCITY"
                                    logger.info(f"{status}: {token['symbol']} | Gain: {gain:.2f}% | Velocity: {velocity:.4f}/s")
                                    await self.log_token_event("performance_alert", {
                                        "mint": mint,
                                        "symbol": token["symbol"],
                                        "gain": gain,
                                        "velocity": velocity,
                                        "current_price": current_price
                                    })
                except Exception as e:
                    logger.error(f"Error in update_prices batch: {e}")

    async def listen_to_pumpportal(self):
        while True:
            try:
                async with websockets.connect(PUMP_WS_URL) as websocket:
                    payload = {"method": "subscribeNewToken"}
                    await websocket.send(json.dumps(payload))
                    logger.info("Subscribed to New Token events")

                    async for message in websocket:
                        data = json.loads(message)
                        if data.get("txType") == "create":
                            # Process concurrently to handle high launch volume
                            asyncio.create_task(self.process_new_token(data))
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting...")
                await asyncio.sleep(5)

    async def trend_loop(self):
        while True:
            logger.info("Refreshing trending keywords from all sources...")
            dex = await self.fetch_trending_dex()
            cg = await self.fetch_trending_coingecko()
            reddit = await self.fetch_trending_reddit()
            # Run google sync in thread to not block event loop
            loop = asyncio.get_event_loop()
            google = await loop.run_in_executor(None, self.fetch_trending_google)

            self.trending_words = dex | cg | reddit | google
            logger.info(f"Unified trending words: {len(self.trending_words)} keywords")
            await asyncio.sleep(600) # Every 10 min

    async def run(self, duration_hours=1):
        logger.info(f"Starting Enhanced Pump Scanner for {duration_hours} hours...")
        tasks = [
            asyncio.create_task(self.listen_to_pumpportal()),
            asyncio.create_task(self.update_prices()),
            asyncio.create_task(self.trend_loop())
        ]
        await asyncio.sleep(duration_hours * 3600)
        for task in tasks: task.cancel()
        logger.info("Scanner finished.")
        # Serialize watchlist without deque
        serializable_watchlist = {}
        for m, data in self.watchlist.items():
            d = data.copy()
            d["price_history"] = list(d["price_history"])
            serializable_watchlist[m] = d
        with open("final_watchlist_enhanced.json", "w") as f:
            json.dump(serializable_watchlist, f, indent=2)
        await self.http_client.aclose()

if __name__ == "__main__":
    scanner = PumpScanner()
    try:
        asyncio.run(scanner.run(duration_hours=1.1))
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user.")
