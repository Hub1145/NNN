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

# Configuration
PUMP_WS_URL = os.getenv("PUMP_WS_URL", "wss://pumpportal.fun/api/data")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "224b9be6-036a-4c57-b4b2-534691844193")
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
LOG_FILE = os.getenv("PUMP_LOG_FILE", "token_data.jsonl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PumpScanner:
    def __init__(self):
        self.watchlist = {} # mint -> token_data
        self.http_client = httpx.AsyncClient(timeout=10.0)

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

    async def get_bonding_curve_state(self, bonding_curve_key):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                bonding_curve_key,
                {"encoding": "jsonParsed"}
            ]
        }
        try:
            response = await self.http_client.post(HELIUS_RPC_URL, json=payload)
            if response.status_code == 200:
                data = response.json()
                if "result" in data and data["result"]["value"]:
                    # Bonding curve data is at the end of the account data
                    # It's a bit complex to parse raw data without the layout
                    # But PumpPortal events give us the reserves directly in trade events!
                    # Maybe it's better to just subscribe to trades if we want real-time.
                    # But user said check for 1hr.
                    return data["result"]["value"]
        except Exception as e:
            logger.error(f"Error fetching account info for {bonding_curve_key}: {e}")
        return None

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
        bonding_curve_key = event.get("bondingCurveKey")
        v_tokens = event.get("vTokensInBondingCurve")
        v_sol = event.get("vSolInBondingCurve")

        logger.info(f"New Token: {name} ({symbol}) - {mint}")

        metadata = await self.fetch_metadata(uri)
        has_website = False
        has_twitter = False
        has_telegram = False

        if metadata:
            has_website = bool(metadata.get("website") or "website" in str(metadata).lower())
            has_twitter = bool(metadata.get("twitter") or "twitter" in str(metadata).lower() or "x.com" in str(metadata).lower())
            has_telegram = bool(metadata.get("telegram") or "t.me" in str(metadata).lower())

        # PumpPortal event gives vSol and vTokens in nominal units (SOL and whole tokens)
        # Bonding curve account data gives them in lamports and base units (6 decimals)
        # We normalize everything to lamports per base unit.

        # event v_tokens is usually 1,073,000,000
        # event v_sol is usually 30
        initial_price = (v_sol * 1e9) / (v_tokens * 1e6) if v_tokens else 0

        token_data = {
            "mint": mint,
            "name": name,
            "symbol": symbol,
            "bonding_curve_key": bonding_curve_key,
            "initial_price": initial_price,
            "current_price": initial_price,
            "max_price": initial_price,
            "v_sol": v_sol,
            "v_tokens": v_tokens,
            "has_website": has_website,
            "has_twitter": has_twitter,
            "has_telegram": has_telegram,
            "created_at": datetime.now().isoformat(),
            "metadata": metadata
        }

        self.watchlist[mint] = token_data
        await self.log_token_event("new_token", token_data)

    async def update_prices(self):
        while True:
            await asyncio.sleep(60) # Update every minute
            logger.info(f"Updating prices for {len(self.watchlist)} tokens...")

            # To avoid hitting rate limits too hard, we could batch or be careful
            # Helius free tier is 10k/day usually, but I have a key.

            # Actually, I can use PumpPortal to subscribe to trades of THESE tokens.
            # But that costs SOL.

            # Alternatively, I can use Helius getMultipleAccounts for bonding curves.
            mints = list(self.watchlist.keys())
            for i in range(0, len(mints), 100):
                batch = mints[i:i+100]
                # Get bonding curve keys for this batch
                keys = [self.watchlist[m]["bonding_curve_key"] for m in batch]

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [
                        keys,
                        {"encoding": "base64"}
                    ]
                }

                try:
                    response = await self.http_client.post(HELIUS_RPC_URL, json=payload)
                    if response.status_code == 200:
                        results = response.json().get("result", {}).get("value", [])
                        for j, res in enumerate(results):
                            if res and res.get("data"):
                                # Parsing pump.fun bonding curve data from base64
                                # Layout:
                                # 8 bytes discriminator
                                # 8 bytes virtualTokenReserves (u64)
                                # 8 bytes virtualSolReserves (u64)
                                # 8 bytes realTokenReserves (u64)
                                # 8 bytes realSolReserves (u64)
                                # 8 bytes tokenTotalSupply (u64)
                                # 1 byte complete (bool)
                                raw_data = base64.b64decode(res["data"][0])
                                if len(raw_data) < 24:
                                    continue
                                # skip 8 bytes discriminator
                                # Pump.fun bonding curve layout:
                                # virtualTokenReserves: u64
                                # virtualSolReserves: u64
                                # realTokenReserves: u64
                                # realSolReserves: u64
                                # tokenTotalSupply: u64
                                v_tokens, v_sol = struct.unpack("<QQ", raw_data[8:24])

                                mint = batch[j]
                                # v_sol is in lamports, v_tokens is in base units (6 decimals)
                                current_price = v_sol / v_tokens if v_tokens else 0

                                # Debug logging for the first few tokens to verify scaling
                                if i == 0 and j < 3:
                                    logger.debug(f"Token {self.watchlist[mint]['symbol']}: v_sol={v_sol}, v_tokens={v_tokens}, price={current_price:.10f}, initial={self.watchlist[mint]['initial_price']:.10f}")

                                self.watchlist[mint]["current_price"] = current_price
                                if current_price > self.watchlist[mint]["max_price"]:
                                    self.watchlist[mint]["max_price"] = current_price

                                # Log progress
                                initial_price = self.watchlist[mint]["initial_price"]
                                if initial_price > 0:
                                    gain = (current_price / initial_price - 1) * 100
                                    if gain >= 100:
                                        logger.info(f"🚀 {self.watchlist[mint]['symbol']} is up {gain:.2f}%! (Price: {current_price:.10f}, Initial: {initial_price:.10f})")
                                    await self.log_token_event("high_gain", {
                                        "mint": mint,
                                        "symbol": self.watchlist[mint]["symbol"],
                                        "gain": gain,
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
                            await self.process_new_token(data)
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting...")
                await asyncio.sleep(5)

    async def run(self, duration_hours=1):
        logger.info(f"Starting Pump Scanner for {duration_hours} hours...")

        # Run listeners and price updater
        tasks = [
            asyncio.create_task(self.listen_to_pumpportal()),
            asyncio.create_task(self.update_prices())
        ]

        # Run for specified duration
        await asyncio.sleep(duration_hours * 3600)

        for task in tasks:
            task.cancel()

        logger.info("Scanner finished. Saving final data...")
        with open("final_watchlist.json", "w") as f:
            json.dump(self.watchlist, f, indent=2)

        await self.http_client.aclose()

if __name__ == "__main__":
    scanner = PumpScanner()
    try:
        asyncio.run(scanner.run(duration_hours=1.1)) # Run slightly more than 1 hour
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user.")
