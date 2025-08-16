import requests
import json
import time
from datetime import datetime
from colorama import Fore, Back, Style, init
import os
import sys

# Initialize colorama for Windows compatibility
init(autoreset=True)

class JupiterPriceTrackerV3:
    def __init__(self, token_address, output_file="price_data.json"):
        self.token_address = token_address
        self.sol_address = "So11111111111111111111111111111111111111112"  # SOL mint address
        self.output_file = output_file
        self.price_data = []
        self.last_price = None
        self.last_sol_price = None
        
        # API endpoints
        self.lite_api_url = "https://lite-api.jup.ag/price/v3"
        self.pro_api_url = "https://api.jup.ag/price/v3"
        self.current_api_url = self.lite_api_url  # Start with lite
        
        # Load existing data if file exists
        self.load_existing_data()
        
        print(f"{Fore.CYAN}{'='*65}")
        print(f"{Fore.YELLOW}🚀 JUPITER PRICE TRACKER V3 (BETA) 🚀")
        print(f"{Fore.CYAN}{'='*65}")
        print(f"{Fore.GREEN}Token: {Fore.WHITE}{token_address}")
        print(f"{Fore.GREEN}Quote: {Fore.WHITE}SOL (derived from USD prices)")
        print(f"{Fore.GREEN}API: {Fore.WHITE}Price API V3 Beta")
        print(f"{Fore.GREEN}Output: {Fore.WHITE}{output_file}")
        print(f"{Fore.CYAN}{'='*65}")
    
    def load_existing_data(self):
        """Load existing price data from JSON file"""
        try:
            if os.path.exists(self.output_file):
                with open(self.output_file, 'r') as f:
                    self.price_data = json.load(f)
                print(f"{Fore.BLUE}📊 Loaded {len(self.price_data)} existing price points")
        except Exception as e:
            print(f"{Fore.RED}❌ Error loading existing data: {e}")
            self.price_data = []
    
    def get_prices_from_jupiter_v3(self):
        """Fetch current prices from Jupiter API V3"""
        try:
            # Request both token and SOL prices
            ids = f"{self.token_address},{self.sol_address}"
            url = f"{self.current_api_url}?ids={ids}"
            
            headers = {
                'Accept': 'application/json',
                'User-Agent': 'Jupiter-Price-Tracker-V3/1.0'
            }
            
            print(f"{Fore.BLUE}🔄 Fetching from: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 429:
                print(f"{Fore.YELLOW}⚠️  Rate limited on {self.current_api_url}")
                if self.current_api_url == self.lite_api_url:
                    print(f"{Fore.CYAN}🔄 Switching to Pro API...")
                    self.current_api_url = self.pro_api_url
                return None, None, None
            
            response.raise_for_status()
            data = response.json()
            
            print(f"{Fore.GREEN}📡 Raw API Response:")
            print(f"{Fore.WHITE}{json.dumps(data, indent=2)}")
            
            # Extract token data
            token_data = data.get(self.token_address)
            sol_data = data.get(self.sol_address)
            
            if not token_data:
                print(f"{Fore.RED}❌ No data found for token: {self.token_address}")
                return None, None, None
            
            if not sol_data:
                print(f"{Fore.RED}❌ No data found for SOL")
                return None, None, None
            
            # Get USD prices
            token_usd_price = float(token_data['usdPrice'])
            sol_usd_price = float(sol_data['usdPrice'])
            
            # Calculate token price in SOL
            token_sol_price = token_usd_price / sol_usd_price
            
            # Get additional info
            block_id = token_data.get('blockId', 'N/A')
            price_change_24h = token_data.get('priceChange24h', 0)
            
            return token_sol_price, {
                'token_usd': token_usd_price,
                'sol_usd': sol_usd_price,
                'block_id': block_id,
                'price_change_24h': price_change_24h,
                'decimals': token_data.get('decimals', 6)
            }, data
                
        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}🔥 Network Error: {e}")
            return None, None, None
        except Exception as e:
            print(f"{Fore.RED}💥 Unexpected Error: {e}")
            return None, None, None
    
    def format_price_change(self, current_price):
        """Format price change with colors"""
        if self.last_price is None:
            return f"{Fore.WHITE}NEW"
        
        change = current_price - self.last_price
        change_percent = (change / self.last_price) * 100 if self.last_price != 0 else 0
        
        if change > 0:
            return f"{Fore.GREEN}↗ +{change:.8f} (+{change_percent:.2f}%)"
        elif change < 0:
            return f"{Fore.RED}↘ {change:.8f} ({change_percent:.2f}%)"
        else:
            return f"{Fore.YELLOW}→ {change:.8f} (0.00%)"
    
    def save_price_data(self):
        """Save price data to JSON file"""
        try:
            with open(self.output_file, 'w') as f:
                json.dump(self.price_data, f, indent=2)
            print(f"{Fore.BLUE}💾 Data saved to {self.output_file}")
        except Exception as e:
            print(f"{Fore.RED}❌ Error saving data: {e}")
    
    def add_price_point(self, price):
        """Add new price point to data"""
        timestamp = datetime.now().isoformat()
        price_point = {
            "timestamp": timestamp,
            "price": price
        }
        self.price_data.append(price_point)
        return price_point
    
    def display_status(self, price, metadata, price_point):
        """Display beautiful status update"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        change_info = self.format_price_change(price)
        
        print(f"\n{Back.BLACK}{Fore.CYAN}⏰ {timestamp} {Style.RESET_ALL}", end=" ")
        print(f"{Back.BLUE}{Fore.WHITE} PRICE UPDATE V3 {Style.RESET_ALL}")
        print(f"{Fore.YELLOW}💰 Token/SOL: {Fore.WHITE}{price:.10f} SOL")
        print(f"{Fore.CYAN}💵 Token USD: {Fore.WHITE}${metadata['token_usd']:.6f}")
        print(f"{Fore.CYAN}💵 SOL USD: {Fore.WHITE}${metadata['sol_usd']:.2f}")
        print(f"{Fore.MAGENTA}📈 Change: {change_info}")
        print(f"{Fore.BLUE}📊 24h Change: {Fore.WHITE}{metadata['price_change_24h']:.2f}%")
        print(f"{Fore.GREEN}🧱 Block ID: {Fore.WHITE}{metadata['block_id']}")
        print(f"{Fore.CYAN}📈 Total Points: {Fore.WHITE}{len(self.price_data)}")
        print(f"{Fore.WHITE}🔗 API: {Fore.YELLOW}{self.current_api_url}")
        print(f"{Fore.GREEN}{'─'*60}")
    
    def run(self, interval=60):
        """Run the price tracker"""
        print(f"\n{Fore.GREEN}🎯 Starting V3 price tracking (interval: {interval}s)")
        print(f"{Fore.YELLOW}Press Ctrl+C to stop gracefully...\n")
        
        try:
            while True:
                price, metadata, raw_data = self.get_prices_from_jupiter_v3()
                
                if price is not None and metadata is not None:
                    price_point = self.add_price_point(price)
                    self.display_status(price, metadata, price_point)
                    self.save_price_data()
                    self.last_price = price
                else:
                    print(f"{Fore.RED}⚠️  Failed to fetch price, retrying in {interval}s...")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print(f"\n\n{Fore.YELLOW}🛑 Tracker stopped by user")
            print(f"{Fore.GREEN}📊 Final stats:")
            print(f"{Fore.CYAN}   Total price points collected: {len(self.price_data)}")
            print(f"{Fore.CYAN}   Data saved to: {self.output_file}")
            print(f"{Fore.CYAN}   API used: {self.current_api_url}")
            print(f"{Fore.MAGENTA}   Thanks for using Jupiter Price Tracker V3! 🚀")
        except Exception as e:
            print(f"{Fore.RED}💥 Fatal error: {e}")
        finally:
            self.save_price_data()

def main():
    # Your token address
    TOKEN_ADDRESS = "FhvBDEr46meW6NHWHNeShDzvbXWabNzyT6uGinEgBAGS"
    
    # Initialize tracker
    tracker = JupiterPriceTrackerV3(TOKEN_ADDRESS, "token_price_data_v3.json")
    
    # Start tracking (60 seconds interval for minute-by-minute)
    tracker.run(interval=60)

if __name__ == "__main__":
    main()