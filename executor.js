const { Connection, Keypair, VersionedTransaction, PublicKey } = require('@solana/web3.js');
const { TOKEN_PROGRAM_ID } = require('@solana/spl-token');
const fetch = require('node-fetch');
const fs = require('fs');

class JupiterExecutor {
  constructor() {
    this.connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
    this.loadConfig();
    this.loadWallet();
    this.loadWalletStats();
    
    // Trade state management
    this.activeTradeSignature = null;
    this.lastTradeTime = null;
    this.tradeCooldownMs = 30000;
    this.confirmationTimeoutMs = 120000;
  }
  
  loadConfig() {
    const configData = fs.readFileSync('bot_config.json', 'utf-8');
    this.config = JSON.parse(configData);
    
    if (!this.config.trading.cooldown_seconds) {
      this.config.trading.cooldown_seconds = 30;
    }
    this.tradeCooldownMs = this.config.trading.cooldown_seconds * 1000;
  }
  
  loadWallet() {
    const keyData = JSON.parse(fs.readFileSync(this.config.wallet.private_key_path, 'utf-8'));
    this.wallet = Keypair.fromSecretKey(new Uint8Array(keyData));
    console.log(`🔑 Loaded wallet: ${this.wallet.publicKey.toString()}`);
  }
  
  loadWalletStats() {
  const statsFile = 'wallet_statistics.json';
  if (fs.existsSync(statsFile)) {
    this.walletStats = JSON.parse(fs.readFileSync(statsFile, 'utf-8'));
    console.log(`📊 Loaded existing wallet statistics`);
    console.log(`📅 Last analysis: ${this.walletStats.last_analysis_timestamp || 'Never'}`);
    console.log(`📊 Last transaction count: ${this.walletStats.last_transaction_count || 'Unknown'}`);
    console.log(`✅ Analysis complete: ${this.walletStats.historical_analysis_complete || false}`);
  } else {
    this.walletStats = {
      wallet_address: this.wallet.publicKey.toString(),
      initial_sol_balance: null,
      first_recorded: new Date().toISOString(),
      total_trades_executed: 0,
      total_sol_spent: 0,
      total_tokens_acquired: 0,
      token_acquisitions: [],
      historical_analysis_complete: false,
      last_transaction_count: 0, // Track total transaction count
      last_analysis_timestamp: null,
      current_position: {
        sol_balance: 0,
        token_balance: 0,
        token_symbol: this.config.tokens ? Object.keys(this.config.tokens)[0] : 'UNKNOWN',
        last_updated: null
      }
    };
  }
}
  
  saveWalletStats() {
    fs.writeFileSync('wallet_statistics.json', JSON.stringify(this.walletStats, null, 2));
  }
  
  async getTokenBalance(tokenMintAddress) {
    try {
      const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
        this.wallet.publicKey,
        { mint: new PublicKey(tokenMintAddress) }
      );
      
      if (tokenAccounts.value.length === 0) {
        return 0;
      }
      
      let totalBalance = 0;
      for (const account of tokenAccounts.value) {
        const balance = account.account.data.parsed.info.tokenAmount.uiAmount;
        totalBalance += balance || 0;
      }
      
      return totalBalance;
    } catch (error) {
      console.error(`❌ Error getting token balance: ${error.message}`);
      return 0;
    }
  }
  
  async getSolBalance() {
    try {
      const balance = await this.connection.getBalance(this.wallet.publicKey);
      return balance / 1e9;
    } catch (error) {
      console.error(`❌ Error getting SOL balance: ${error.message}`);
      return 0;
    }
  }
  
 async analyzeHistoricalTransactions() {
  console.log('🔍 Checking for transaction changes...');
  
  try {
    // Get current transaction count (just the count, not all the data)
    const currentSignatures = await this.connection.getSignaturesForAddress(
      this.wallet.publicKey,
      { limit: 1000 }
    );
    
    const currentTransactionCount = currentSignatures.length;
    console.log(`📜 Current transaction count: ${currentTransactionCount}`);
    
    // Check if we have a previous count recorded
    const previousCount = this.walletStats.last_transaction_count || 0;
    const analysisComplete = this.walletStats.historical_analysis_complete || false;
    
    console.log(`📊 Previous count: ${previousCount}`);
    console.log(`✅ Analysis complete: ${analysisComplete}`);
    
    // If analysis is complete AND transaction count hasn't changed, skip entirely
    if (analysisComplete && currentTransactionCount === previousCount) {
      console.log('🎉 No new transactions detected - skipping analysis');
      console.log(`📋 Wallet stats are up to date with ${this.walletStats.total_trades_executed} acquisitions`);
      return;
    }
    
    // If transaction count has changed, we need to analyze
    if (currentTransactionCount > previousCount) {
      const newTransactionCount = currentTransactionCount - previousCount;
      console.log(`🆕 Found ${newTransactionCount} new transactions to analyze`);
      
      // Only analyze the NEW transactions (the ones at the beginning of the array)
      const newTransactionsToAnalyze = currentSignatures.slice(0, newTransactionCount);
      
      await this.processTransactionBatch(newTransactionsToAnalyze, 'incremental');
      
    } else if (currentTransactionCount < previousCount) {
      console.log('⚠️ Transaction count decreased - this is unusual');
      console.log('🔄 Running full re-analysis to be safe');
      
      // Reset everything and do full analysis
      this.resetWalletStats();
      await this.processTransactionBatch(currentSignatures, 'full');
      
    } else if (!analysisComplete) {
      console.log('🔄 Analysis was incomplete - running full analysis');
      await this.processTransactionBatch(currentSignatures, 'full');
    }
    
    // Update our tracking info
    this.walletStats.last_transaction_count = currentTransactionCount;
    this.walletStats.last_analysis_timestamp = new Date().toISOString();
    this.walletStats.historical_analysis_complete = true;
    
    this.recalculateStats();
    this.saveWalletStats();
    
  } catch (error) {
    console.error(`❌ Error in transaction analysis: ${error.message}`);
  }
}

// Helper method to reset wallet stats for full re-analysis
resetWalletStats() {
  this.walletStats.token_acquisitions = [];
  this.walletStats.total_trades_executed = 0;
  this.walletStats.total_sol_spent = 0;
  this.walletStats.total_tokens_acquired = 0;
  this.walletStats.historical_analysis_complete = false;
  console.log('🔄 Reset wallet stats for fresh analysis');
}

// Helper method to process a batch of transactions
async processTransactionBatch(transactionsToAnalyze, analysisType) {
  if (transactionsToAnalyze.length === 0) {
    console.log('📋 No transactions to process');
    return;
  }
  
  console.log(`⏱️ Processing ${transactionsToAnalyze.length} transactions (${analysisType} analysis)...`);
  console.log(`⏱️ Estimated time: ${Math.ceil(transactionsToAnalyze.length * 3 / 60)} minutes with rate limiting`);
  
  const tokenMintAddress = this.config.tokens[Object.keys(this.config.tokens)[0]];
  let newAcquisitionsFound = 0;
  let requestCount = 0;
  
  for (let i = 0; i < transactionsToAnalyze.length; i++) {
    const sigInfo = transactionsToAnalyze[i];
    
    try {
      console.log(`🔍 ${analysisType === 'incremental' ? 'NEW' : ''} Transaction ${i + 1}/${transactionsToAnalyze.length}: ${sigInfo.signature.substring(0, 8)}...`);
      
      const transaction = await this.connection.getParsedTransaction(sigInfo.signature, {
        maxSupportedTransactionVersion: 0
      });
      
      requestCount++;
      
      if (!transaction || !transaction.meta) {
        console.log(`   ⚠️ No transaction data found`);
      } else {
        const tokenAcquisition = this.parseTokenAcquisition(transaction, tokenMintAddress);
        if (tokenAcquisition) {
          // For incremental analysis, check for duplicates
          // For full analysis, we already reset so no need to check
          const existingAcquisition = analysisType === 'incremental' ? 
            this.walletStats.token_acquisitions.find(
              acq => acq.transaction_signature === tokenAcquisition.transaction_signature
            ) : null;
          
          if (!existingAcquisition) {
            this.walletStats.token_acquisitions.push(tokenAcquisition);
            newAcquisitionsFound++;
            console.log(`   ✅ ${analysisType === 'incremental' ? 'NEW' : ''} acquisition: ${tokenAcquisition.tokens_received.toLocaleString()} tokens for ${tokenAcquisition.sol_spent.toFixed(4)} SOL`);
          } else {
            console.log(`   ➖ Acquisition already recorded (duplicate)`);
          }
        } else {
          console.log(`   ➖ No token acquisition found`);
        }
      }
      
      // Save progress every 5 transactions
      if ((i + 1) % 5 === 0) {
        this.recalculateStats();
        this.saveWalletStats();
        console.log(`💾 Progress saved: ${newAcquisitionsFound} ${analysisType === 'incremental' ? 'new ' : ''}acquisitions found`);
      }
      
      // Rate limiting
      if (i < transactionsToAnalyze.length - 1) {
        console.log(`   ⏳ Waiting 3 seconds...`);
        await new Promise(resolve => setTimeout(resolve, 3000));
      }
      
      // Extra delay every 15 requests
      if (requestCount % 15 === 0) {
        console.log(`🛑 Taking a 15-second break after ${requestCount} requests...`);
        await new Promise(resolve => setTimeout(resolve, 15000));
      }
      
    } catch (error) {
      console.error(`⚠️ Error analyzing transaction ${sigInfo.signature}: ${error.message}`);
      
      if (error.message.includes('429') || error.message.includes('Too Many Requests')) {
        console.log(`🚫 Rate limited! Waiting 45 seconds...`);
        await new Promise(resolve => setTimeout(resolve, 45000));
      } else {
        await new Promise(resolve => setTimeout(resolve, 5000));
      }
    }
  }
  
  console.log(`✅ ${analysisType} analysis complete!`);
  console.log(`🆕 Found ${newAcquisitionsFound} ${analysisType === 'incremental' ? 'new ' : ''}acquisitions`);
}

// Keep the existing recalculateStats method
recalculateStats() {
  this.walletStats.token_acquisitions.sort((a, b) => 
    new Date(a.timestamp) - new Date(b.timestamp)
  );
  
  this.walletStats.total_trades_executed = this.walletStats.token_acquisitions.length;
  this.walletStats.total_sol_spent = this.walletStats.token_acquisitions.reduce(
    (sum, acq) => sum + acq.sol_spent, 0
  );
  this.walletStats.total_tokens_acquired = this.walletStats.token_acquisitions.reduce(
    (sum, acq) => sum + acq.tokens_received, 0
  );
  
  if (this.walletStats.total_tokens_acquired > 0) {
    this.walletStats.average_entry_price = this.walletStats.total_sol_spent / this.walletStats.total_tokens_acquired;
  }
}

// Helper method to recalculate all stats from acquisitions
recalculateStats() {
  // Sort acquisitions by timestamp (oldest first)
  this.walletStats.token_acquisitions.sort((a, b) => 
    new Date(a.timestamp) - new Date(b.timestamp)
  );
  
  // Recalculate totals
  this.walletStats.total_trades_executed = this.walletStats.token_acquisitions.length;
  this.walletStats.total_sol_spent = this.walletStats.token_acquisitions.reduce(
    (sum, acq) => sum + acq.sol_spent, 0
  );
  this.walletStats.total_tokens_acquired = this.walletStats.token_acquisitions.reduce(
    (sum, acq) => sum + acq.tokens_received, 0
  );
  
  if (this.walletStats.total_tokens_acquired > 0) {
    this.walletStats.average_entry_price = this.walletStats.total_sol_spent / this.walletStats.total_tokens_acquired;
  }
}
  
  parseTokenAcquisition(transaction, targetTokenMint) {
    try {
      if (!transaction.meta || !transaction.meta.postTokenBalances) return null;
      
      // Look for increases in token balance for our target token
      for (const postBalance of transaction.meta.postTokenBalances) {
        if (postBalance.mint !== targetTokenMint || 
            postBalance.owner !== this.wallet.publicKey.toString()) {
          continue;
        }
        
        // Find corresponding pre-balance
        const preBalance = transaction.meta.preTokenBalances?.find(
          pre => pre.accountIndex === postBalance.accountIndex
        );
        
        const preAmount = preBalance ? preBalance.uiTokenAmount.uiAmount : 0;
        const postAmount = postBalance.uiTokenAmount.uiAmount;
        
        if (postAmount > preAmount) {
          const tokensReceived = postAmount - preAmount;
          
          // Calculate SOL spent by looking at SOL balance changes
          const preSolBalance = (transaction.meta.preBalances[0] || 0) / 1e9;
          const postSolBalance = (transaction.meta.postBalances[0] || 0) / 1e9;
          const solSpent = Math.max(0, preSolBalance - postSolBalance);
          
          // Skip if no meaningful SOL was spent (might be a transfer/airdrop)
          if (solSpent < 0.001) continue;
          
          return {
            timestamp: transaction.blockTime ? new Date(transaction.blockTime * 1000).toISOString() : new Date().toISOString(),
            transaction_signature: transaction.transaction.signatures[0],
            sol_spent: solSpent,
            tokens_received: tokensReceived,
            price_per_token: solSpent / tokensReceived,
            block_time: transaction.blockTime,
            source: 'historical_analysis'
          };
        }
      }
      
      return null;
    } catch (error) {
      console.error(`Error parsing transaction: ${error.message}`);
      return null;
    }
  }
  
  async getCurrentTokenPrice() {
    try {
      // Use Jupiter API to get current price by getting a small quote
      const tokenAddress = this.config.tokens[Object.keys(this.config.tokens)[0]];
      const SOL_MINT = 'So11111111111111111111111111111111111111112';
      
      // Get price for 1 SOL worth of tokens
      const quote = await this.getJupiterQuote(SOL_MINT, tokenAddress, 1e9, 100);
      const tokensFor1Sol = parseInt(quote.outAmount);
      const pricePerToken = 1 / tokensFor1Sol; // SOL per token
      
      return pricePerToken;
    } catch (error) {
      console.error(`❌ Error getting current token price: ${error.message}`);
      return null;
    }
  }
  
  async updateWalletBalances() {
    try {
      console.log('📊 Updating wallet balances...');
      
      const solBalance = await this.getSolBalance();
      let tokenBalance = 0;
      let tokenSymbol = 'UNKNOWN';
      
      if (this.config.tokens) {
        const tokens = Object.entries(this.config.tokens);
        if (tokens.length > 0) {
          tokenSymbol = tokens[0][0];
          const tokenAddress = tokens[0][1];
          tokenBalance = await this.getTokenBalance(tokenAddress);
        }
      }
      
      // Set initial SOL balance if not set (estimate based on current + spent)
      if (this.walletStats.initial_sol_balance === null) {
        const estimatedInitial = solBalance + (this.walletStats.total_sol_spent || 0);
        this.walletStats.initial_sol_balance = estimatedInitial;
        console.log(`🆕 Estimated initial SOL balance: ${estimatedInitial.toFixed(4)} SOL`);
        console.log(`    (Current: ${solBalance.toFixed(4)} + Historical spent: ${(this.walletStats.total_sol_spent || 0).toFixed(4)})`);
      }
      
      // Update current position
      this.walletStats.current_position = {
        sol_balance: solBalance,
        token_balance: tokenBalance,
        token_symbol: tokenSymbol,
        last_updated: new Date().toISOString()
      };
      
      // Calculate comprehensive performance metrics
      const solChange = solBalance - this.walletStats.initial_sol_balance;
      
      // Get current token price and calculate token value
      const currentTokenPrice = await this.getCurrentTokenPrice();
      let tokenValueInSol = 0;
      
      if (currentTokenPrice && tokenBalance > 0) {
        tokenValueInSol = tokenBalance * currentTokenPrice;
        console.log(`💎 Token value: ${tokenBalance.toLocaleString()} × ${currentTokenPrice.toFixed(10)} = ${tokenValueInSol.toFixed(4)} SOL`);
      }
      
      const totalCurrentValue = solBalance + tokenValueInSol;
      const totalPnL = totalCurrentValue - this.walletStats.initial_sol_balance;
      const performancePercent = (totalPnL / this.walletStats.initial_sol_balance) * 100;
      
      // Calculate realized vs unrealized P&L
      const realizedPnL = this.walletStats.initial_sol_balance - this.walletStats.total_sol_spent - solBalance;
      const unrealizedPnL = tokenValueInSol - this.walletStats.total_sol_spent;
      
      this.walletStats.performance = {
        sol_change: solChange,
        total_pnl: totalPnL,
        total_pnl_percent: performancePercent,
        total_current_value: totalCurrentValue,
        token_value_in_sol: tokenValueInSol,
        current_token_price: currentTokenPrice,
        realized_pnl: realizedPnL,
        unrealized_pnl: unrealizedPnL,
        average_entry_price: this.walletStats.average_entry_price || 0
      };
      
      console.log(`💰 SOL Balance: ${solBalance.toFixed(4)}`);
      console.log(`🪙 ${tokenSymbol} Balance: ${tokenBalance.toLocaleString()}`);
      console.log(`💎 Token Value: ${tokenValueInSol.toFixed(4)} SOL`);
      console.log(`📊 Total Value: ${totalCurrentValue.toFixed(4)} SOL`);
      console.log(`📈 Total P&L: ${totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(4)} SOL (${performancePercent >= 0 ? '+' : ''}${performancePercent.toFixed(2)}%)`);
      
      if (this.walletStats.average_entry_price && currentTokenPrice) {
        const priceChange = ((currentTokenPrice - this.walletStats.average_entry_price) / this.walletStats.average_entry_price) * 100;
        console.log(`🎯 Price vs Entry: ${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%`);
      }
      
      this.saveWalletStats();
      
    } catch (error) {
      console.error(`❌ Error updating wallet balances: ${error.message}`);
    }
  }
  
  generateWalletReport() {
    const stats = this.walletStats;
    const current = stats.current_position;
    const perf = stats.performance || {};
    
    console.log('\n📊 === COMPREHENSIVE WALLET REPORT ===');
    console.log(`🏦 Wallet: ${stats.wallet_address}`);
    console.log(`📅 First Recorded: ${new Date(stats.first_recorded).toLocaleString()}`);
    console.log(`🔍 Historical Analysis: ${stats.historical_analysis_complete ? '✅ Complete' : '❌ Pending'}`);
    
    console.log(`\n💰 CURRENT BALANCES:`);
    console.log(`   SOL: ${current.sol_balance?.toFixed(4)}`);
    console.log(`   ${current.token_symbol}: ${current.token_balance?.toLocaleString()}`);
    if (perf.token_value_in_sol) {
      console.log(`   Token Value: ${perf.token_value_in_sol.toFixed(4)} SOL`);
      console.log(`   Total Value: ${perf.total_current_value?.toFixed(4)} SOL`);
    }
    
    console.log(`\n📊 INITIAL VS CURRENT:`);
    console.log(`   Initial SOL: ${stats.initial_sol_balance?.toFixed(4)}`);
    console.log(`   Current Total: ${perf.total_current_value?.toFixed(4)} SOL`);
    
    if (perf.total_pnl !== undefined) {
      console.log(`\n📈 PERFORMANCE:`);
      console.log(`   Total P&L: ${perf.total_pnl >= 0 ? '+' : ''}${perf.total_pnl?.toFixed(4)} SOL`);
      console.log(`   Percentage: ${perf.total_pnl_percent >= 0 ? '+' : ''}${perf.total_pnl_percent?.toFixed(2)}%`);
      
      if (perf.unrealized_pnl !== undefined) {
        console.log(`   Unrealized P&L: ${perf.unrealized_pnl >= 0 ? '+' : ''}${perf.unrealized_pnl?.toFixed(4)} SOL`);
      }
    }
    
    console.log(`\n🎯 TRADING HISTORY:`);
    console.log(`   Total Acquisitions: ${stats.total_trades_executed}`);
    console.log(`   SOL Invested: ${stats.total_sol_spent?.toFixed(4)}`);
    console.log(`   Tokens Acquired: ${stats.total_tokens_acquired?.toLocaleString()}`);
    
    if (stats.average_entry_price && perf.current_token_price) {
      console.log(`   Avg Entry Price: ${stats.average_entry_price.toFixed(10)} SOL`);
      console.log(`   Current Price: ${perf.current_token_price.toFixed(10)} SOL`);
      const priceChange = ((perf.current_token_price - stats.average_entry_price) / stats.average_entry_price) * 100;
      console.log(`   Price Change: ${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%`);
    }
    
    console.log(`\n🕐 Last Updated: ${current.last_updated ? new Date(current.last_updated).toLocaleString() : 'Never'}`);
    console.log('=========================================\n');
  }
  
  // ... (keep all existing trade execution methods)
  
  isInCooldown() {
    if (!this.lastTradeTime) return false;
    const timeSinceLastTrade = Date.now() - this.lastTradeTime;
    return timeSinceLastTrade < this.tradeCooldownMs;
  }
  
  getCooldownRemaining() {
    if (!this.lastTradeTime) return 0;
    const timeSinceLastTrade = Date.now() - this.lastTradeTime;
    return Math.max(0, this.tradeCooldownMs - timeSinceLastTrade);
  }
  
  async waitForConfirmation(signature) {
    console.log(`⏳ Waiting for confirmation of ${signature}...`);
    
    const startTime = Date.now();
    const timeout = this.confirmationTimeoutMs;
    
    while (Date.now() - startTime < timeout) {
      try {
        const confirmation = await this.connection.getSignatureStatus(signature, {
          searchTransactionHistory: true
        });
        
        if (confirmation?.value?.confirmationStatus) {
          const status = confirmation.value.confirmationStatus;
          console.log(`📊 Transaction status: ${status}`);
          
          if (status === 'confirmed' || status === 'finalized') {
            if (confirmation.value.err) {
              throw new Error(`Transaction failed: ${JSON.stringify(confirmation.value.err)}`);
            }
            console.log(`✅ Transaction confirmed: ${signature}`);
            return true;
          }
        }
        
        await new Promise(resolve => setTimeout(resolve, 3000));
        
      } catch (error) {
        console.error(`❌ Error checking confirmation: ${error.message}`);
      }
    }
    
    throw new Error(`Transaction confirmation timeout after ${timeout/1000} seconds`);
  }
  
  async getJupiterQuote(inputMint, outputMint, amount, slippageBps = 100) {
    const url = `${this.config.jupiter.api_url}/quote?inputMint=${inputMint}&outputMint=${outputMint}&amount=${amount}&slippageBps=${slippageBps}`;
    
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Jupiter quote failed: ${response.statusText}`);
    }
    
    return await response.json();
  }
  
  async getJupiterSwapTransaction(quoteResponse) {
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
  
  async analyzeTokenAcquisition(signature, solSpent, expectedTokens) {
    try {
      console.log(`🔍 Analyzing transaction: ${signature}`);
      
      await new Promise(resolve => setTimeout(resolve, 5000));
      
      const transaction = await this.connection.getParsedTransaction(signature, {
        maxSupportedTransactionVersion: 0
      });
      
      if (!transaction) {
        console.log('⚠️ Could not retrieve transaction details');
        return null;
      }
      
      let actualTokensReceived = 0;
      let actualPricePerToken = 0;
      
      if (transaction.meta && transaction.meta.postTokenBalances) {
        for (const tokenBalance of transaction.meta.postTokenBalances) {
          if (tokenBalance.owner === this.wallet.publicKey.toString()) {
            const preBalance = transaction.meta.preTokenBalances?.find(
              pre => pre.accountIndex === tokenBalance.accountIndex
            );
            const preAmount = preBalance ? preBalance.uiTokenAmount.uiAmount : 0;
            const postAmount = tokenBalance.uiTokenAmount.uiAmount;
            
            if (postAmount > preAmount) {
              actualTokensReceived = postAmount - preAmount;
              actualPricePerToken = solSpent / actualTokensReceived;
              break;
            }
          }
        }
      }
      
      const acquisition = {
        timestamp: new Date().toISOString(),
        transaction_signature: signature,
        sol_spent: solSpent,
        tokens_received: actualTokensReceived || expectedTokens,
        price_per_token: actualPricePerToken || (solSpent / expectedTokens),
        expected_tokens: expectedTokens,
        slippage: actualTokensReceived ? ((expectedTokens - actualTokensReceived) / expectedTokens) * 100 : 0,
        block_time: transaction.blockTime ? new Date(transaction.blockTime * 1000).toISOString() : null,
        source: 'live_trading'
      };
      
      this.walletStats.token_acquisitions.push(acquisition);
      this.walletStats.total_trades_executed++;
      this.walletStats.total_sol_spent += solSpent;
      this.walletStats.total_tokens_acquired += acquisition.tokens_received;
      
      this.walletStats.average_entry_price = this.walletStats.total_sol_spent / this.walletStats.total_tokens_acquired;
      
      console.log(`📈 Acquisition recorded: ${acquisition.tokens_received.toLocaleString()} tokens at ${acquisition.price_per_token.toFixed(10)} SOL each`);
      
      this.saveWalletStats();
      return acquisition;
      
    } catch (error) {
      console.error(`❌ Error analyzing token acquisition: ${error.message}`);
      return null;
    }
  }
  
  async executeBuyTrade(command) {
    try {
      if (this.activeTradeSignature) {
        console.log(`⏸️ Trade already in progress: ${this.activeTradeSignature}`);
        return {
          success: false,
          error: "Trade already in progress - waiting for confirmation",
          timestamp: new Date().toISOString(),
          sol_spent: 0
        };
      }
      
      if (this.isInCooldown()) {
        const remainingMs = this.getCooldownRemaining();
        console.log(`🕒 Trade cooldown active - ${Math.ceil(remainingMs/1000)}s remaining`);
        return {
          success: false,
          error: `Cooldown active - ${Math.ceil(remainingMs/1000)} seconds remaining`,
          timestamp: new Date().toISOString(),
          sol_spent: 0
        };
      }
      
      console.log(`🚀 Executing BUY: ${command.sol_amount} SOL → ${command.token_symbol}`);
      
      const SOL_MINT = 'So11111111111111111111111111111111111111112';
      const solAmountLamports = command.sol_amount * 1e9;
      
      console.log('📊 Getting Jupiter quote...');
      const quote = await this.getJupiterQuote(
        SOL_MINT,
        command.token_address,
        solAmountLamports,
        this.config.trading.slippage_bps
      );
      
      const expectedTokens = parseInt(quote.outAmount);
      console.log(`📈 Quote: ${command.sol_amount} SOL → ~${expectedTokens.toLocaleString()} ${command.token_symbol}`);
      
      console.log('🔄 Creating swap transaction...');
      const swapResult = await this.getJupiterSwapTransaction(quote);
      
      const transaction = VersionedTransaction.deserialize(
        Buffer.from(swapResult.swapTransaction, 'base64')
      );
      
      transaction.sign([this.wallet]);
      
      console.log('📤 Sending transaction...');
      const signature = await this.connection.sendTransaction(transaction, {
        maxRetries: 3,
        preflightCommitment: 'confirmed',
      });
      
      console.log(`✅ Transaction sent: ${signature}`);
      
      this.activeTradeSignature = signature;
      
      try {
        await this.waitForConfirmation(signature);
        
        this.activeTradeSignature = null;
        this.lastTradeTime = Date.now();
        
        console.log(`🎉 Trade completed successfully: ${signature}`);
        
        const acquisition = await this.analyzeTokenAcquisition(signature, command.sol_amount, expectedTokens);
        
        await this.updateWalletBalances();
        
        this.generateWalletReport();
        
        const tokensReceived = acquisition ? acquisition.tokens_received : expectedTokens;
        const pricePerToken = acquisition ? acquisition.price_per_token : (command.sol_amount / expectedTokens);
        
        return {
          success: true,
          signature,
          timestamp: new Date().toISOString(),
          sol_spent: command.sol_amount,
          tokens_received: tokensReceived,
          price_per_token: pricePerToken,
          acquisition_data: acquisition
        };
        
      } catch (confirmationError) {
        this.activeTradeSignature = null;
        console.error(`❌ Trade confirmation failed: ${confirmationError.message}`);
        
        return {
          success: false,
          signature: signature,
          error: `Confirmation failed: ${confirmationError.message}`,
          timestamp: new Date().toISOString(),
          sol_spent: command.sol_amount
        };
      }
      
    } catch (error) {
      this.activeTradeSignature = null;
      console.error(`❌ Buy trade failed:`, error);
      return {
        success: false,
        error: error.message,
        timestamp: new Date().toISOString(),
        sol_spent: 0
      };
    }
  }
  
  logTrade(command, result) {
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
  
  async processPendingTrades() {
    const pendingFile = 'pending_trades.json';
    
    if (!fs.existsSync(pendingFile)) {
      return;
    }
    
    let pendingTrades = JSON.parse(fs.readFileSync(pendingFile, 'utf-8'));
    let processed = false;
    
    const unprocessedTrades = pendingTrades.filter(trade => !trade.processed);
    
    if (unprocessedTrades.length > 0 && this.config.trading.enabled) {
      const trade = unprocessedTrades[0];
      
      console.log(`\n🔄 Processing trade command: ${trade.command}`);
      console.log(`📊 Queue: ${unprocessedTrades.length} pending trades`);
      
      if (trade.command === 'BUY') {
        const result = await this.executeBuyTrade(trade);
        this.logTrade(trade, result);
        
        trade.processed = true;
        trade.result = result;
        processed = true;
        
        if (result.success) {
          console.log(`⏸️ Trade successful - enforcing cooldown before next trade`);
        } else {
          console.log(`❌ Trade failed: ${result.error}`);
        }
      }
    }
    
    if (processed) {
      const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
      pendingTrades = pendingTrades.filter(trade => 
        !trade.processed || new Date(trade.timestamp) > oneHourAgo
      );
      
      fs.writeFileSync(pendingFile, JSON.stringify(pendingTrades, null, 2));
    }
  }
  
  async start() {
    console.log('🤖 Jupiter Executor started...');
    console.log(`💰 SOL per trade: ${this.config.trading.sol_amount_per_trade}`);
    console.log(`📊 Slippage: ${this.config.trading.slippage_bps / 100}%`);
    console.log(`🕒 Trade cooldown: ${this.config.trading.cooldown_seconds || 30}s`);
    console.log(`🚀 Trading enabled: ${this.config.trading.enabled}`);
    
    // Run historical analysis first
    await this.analyzeHistoricalTransactions();
    
    // Update wallet balances
    await this.updateWalletBalances();
    this.generateWalletReport();
    
    // Update balances every 60 seconds
    setInterval(async () => {
      try {
        await this.updateWalletBalances();
      } catch (error) {
        console.error('❌ Error in periodic balance update:', error);
      }
    }, 60000);
    
    // Process pending trades every 3 seconds
    setInterval(async () => {
      try {
        await this.processPendingTrades();
      } catch (error) {
        console.error('❌ Error processing trades:', error);
      }
    }, 3000);
  }
}

// Start the executor
const executor = new JupiterExecutor();
executor.start();