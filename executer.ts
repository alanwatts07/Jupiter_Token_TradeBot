import { Connection, Keypair, VersionedTransaction } from '@solana/web3.js';
import fetch from 'node-fetch';
import fs from 'fs';

interface BotConfig {
  trading: {
    sol_amount_per_trade: number;
    slippage_bps: number;
    priority_fee_lamports: number;
    enabled: boolean;
  };
  wallet: {
    private_key_path: string;
  };
  tokens: Record<string, string>;
  jupiter: {
    api_url: string;
  };
}

interface TradeCommand {
  command: string;
  timestamp: string;
  token_symbol: string;
  token_address: string;
  sol_amount: number;
  current_price: number;
  trigger_data: any;
  processed: boolean;
}

interface TradeResult {
  success: boolean;
  signature?: string;
  error?: string;
  timestamp: string;
  sol_spent: number;
  tokens_received?: number;
  price_per_token?: number;
}

class JupiterExecutor {
  private connection: Connection;
  private wallet: Keypair;
  private config: BotConfig;
  
  constructor() {
    this.connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
    this.loadConfig();
    this.loadWallet();
  }
  
  private loadConfig(): void {
    const configData = fs.readFileSync('bot_config.json', 'utf-8');
    this.config = JSON.parse(configData);
  }
  
  private loadWallet(): void {
    const keyData = JSON.parse(fs.readFileSync(this.config.wallet.private_key_path, 'utf-8'));
    this.wallet = Keypair.fromSecretKey(new Uint8Array(keyData));
    console.log(`🔑 Loaded wallet: ${this.wallet.publicKey.toString()}`);
  }
  
  private async getJupiterQuote(
    inputMint: string,
    outputMint: string,
    amount: number,
    slippageBps: number = 100
  ) {
    const url = `${this.config.jupiter.api_url}/quote?inputMint=${inputMint}&outputMint=${outputMint}&amount=${amount}&slippageBps=${slippageBps}`;
    
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Jupiter quote failed: ${response.statusText}`);
    }
    
    return await response.json();
  }
  
  private async getJupiterSwapTransaction(quoteResponse: any) {
    const swapResponse = await fetch(`${this.config.jupiter.api_url}/swap`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        quoteResponse,
        userPublicKey: this.wallet.publicKey.toString(),
        wrapAndUnwrapSol: true,
        dynamicComputeUnitLimit: true,
        prioritizationFeeLamports: this.config.trading.priority_fee_lamports,
      }),
    });
    
    if (!swapResponse.ok) {
      throw new Error(`Jupiter swap failed: ${swapResponse.statusText}`);
    }
    
    return await swapResponse.json();
  }
  
  private async executeBuyTrade(command: TradeCommand): Promise<TradeResult> {
    try {
      console.log(`🚀 Executing BUY: ${command.sol_amount} SOL → ${command.token_symbol}`);
      
      const SOL_MINT = 'So11111111111111111111111111111111111111112';
      const solAmountLamports = command.sol_amount * 1e9; // Convert SOL to lamports
      
      // Get quote
      console.log('📊 Getting Jupiter quote...');
      const quote = await this.getJupiterQuote(
        SOL_MINT,
        command.token_address,
        solAmountLamports,
        this.config.trading.slippage_bps
      );
      
      console.log(`📈 Quote: ${command.sol_amount} SOL → ~${parseInt(quote.outAmount)} ${command.token_symbol}`);
      
      // Get swap transaction
      console.log('🔄 Creating swap transaction...');
      const swapResult = await this.getJupiterSwapTransaction(quote);
      
      // Deserialize and sign transaction
      const transaction = VersionedTransaction.deserialize(
        Buffer.from(swapResult.swapTransaction, 'base64')
      );
      
      transaction.sign([this.wallet]);
      
      // Send transaction
      console.log('📤 Sending transaction...');
      const signature = await this.connection.sendTransaction(transaction, {
        maxRetries: 3,
        preflightCommitment: 'confirmed',
      });
      
      console.log(`✅ Transaction sent: ${signature}`);
      
      // Wait for confirmation
      const confirmation = await this.connection.confirmTransaction(signature, 'confirmed');
      
      if (confirmation.value.err) {
        throw new Error(`Transaction failed: ${JSON.stringify(confirmation.value.err)}`);
      }
      
      console.log(`🎉 Trade confirmed: ${signature}`);
      
      // Calculate results
      const tokensReceived = parseInt(quote.outAmount);
      const pricePerToken = command.sol_amount / tokensReceived;
      
      return {
        success: true,
        signature,
        timestamp: new Date().toISOString(),
        sol_spent: command.sol_amount,
        tokens_received: tokensReceived,
        price_per_token: pricePerToken
      };
      
    } catch (error) {
      console.error(`❌ Buy trade failed:`, error);
      return {
        success: false,
        error: error.message,
        timestamp: new Date().toISOString(),
        sol_spent: 0
      };
    }
  }
  
  private logTrade(command: TradeCommand, result: TradeResult): void {
    const logEntry = {
      timestamp: result.timestamp,
      command: command,
      result: result,
    };
    
    let tradeLog = [];
    if (fs.existsSync('jupiter_trade_log.json')) {
      tradeLog = JSON.parse(fs.readFileSync('jupiter_trade_log.json', 'utf-8'));
    }
    
    tradeLog.push(logEntry);
    
    fs.writeFileSync('jupiter_trade_log.json', JSON.stringify(tradeLog, null, 2));
    console.log('📝 Trade logged to jupiter_trade_log.json');
  }
  
  public async processPendingTrades(): Promise<void> {
    const pendingFile = 'pending_trades.json';
    
    if (!fs.existsSync(pendingFile)) {
      return;
    }
    
    let pendingTrades: TradeCommand[] = JSON.parse(fs.readFileSync(pendingFile, 'utf-8'));
    let processed = false;
    
    for (const trade of pendingTrades) {
      if (!trade.processed && this.config.trading.enabled) {
        console.log(`\n🔄 Processing trade command: ${trade.command}`);
        
        if (trade.command === 'BUY') {
          const result = await this.executeBuyTrade(trade);
          this.logTrade(trade, result);
          
          trade.processed = true;
          processed = true;
          
          // Small delay between trades
          await new Promise(resolve => setTimeout(resolve, 2000));
        }
      }
    }
    
    if (processed) {
      // Remove processed trades older than 1 hour
      const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
      pendingTrades = pendingTrades.filter(trade => 
        !trade.processed || new Date(trade.timestamp) > oneHourAgo
      );
      
      fs.writeFileSync(pendingFile, JSON.stringify(pendingTrades, null, 2));
    }
  }
  
  public async start(): void {
    console.log('🤖 Jupiter Executor started...');
    console.log(`💰 SOL per trade: ${this.config.trading.sol_amount_per_trade}`);
    console.log(`📊 Slippage: ${this.config.trading.slippage_bps / 100}%`);
    console.log(`🚀 Trading enabled: ${this.config.trading.enabled}`);
    
    // Process pending trades every 2 seconds
    setInterval(async () => {
      try {
        await this.processPendingTrades();
      } catch (error) {
        console.error('❌ Error processing trades:', error);
      }
    }, 2000);
  }
}

// Start the executor
const executor = new JupiterExecutor();
executor.start();