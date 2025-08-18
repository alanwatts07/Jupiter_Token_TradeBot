const { Connection, Keypair, VersionedTransaction, PublicKey } = require('@solana/web3.js');
const fetch = require('node-fetch');
const fs = require('fs');
const readline = require('readline');

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function question(prompt) {
    return new Promise((resolve) => {
        rl.question(prompt, resolve);
    });
}

class BailoutSeller {
    constructor() {
        this.connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');
        this.loadConfig();
        this.loadWallet();
    }
    
    loadConfig() {
        const configData = fs.readFileSync('bot_config.json', 'utf-8');
        this.config = JSON.parse(configData);
    }
    
    loadWallet() {
        const keyData = JSON.parse(fs.readFileSync(this.config.wallet.private_key_path, 'utf-8'));
        this.wallet = Keypair.fromSecretKey(new Uint8Array(keyData));
        console.log(`🔑 Loaded wallet: ${this.wallet.publicKey.toString()}`);
    }
    
    async getTokenAccountInfo(tokenMintAddress) {
        try {
            const tokenAccounts = await this.connection.getParsedTokenAccountsByOwner(
                this.wallet.publicKey,
                { mint: new PublicKey(tokenMintAddress) }
            );
            
            if (tokenAccounts.value.length === 0) {
                return { balance: 0, decimals: 6, rawAmount: 0 };
            }
            
            let totalBalance = 0;
            let totalRawAmount = 0;
            let decimals = 6; // Default fallback
            
            for (const account of tokenAccounts.value) {
                const accountInfo = account.account.data.parsed.info;
                const balance = accountInfo.tokenAmount.uiAmount || 0;
                const rawAmount = parseInt(accountInfo.tokenAmount.amount);
                decimals = accountInfo.tokenAmount.decimals;
                
                totalBalance += balance;
                totalRawAmount += rawAmount;
            }
            
            return { 
                balance: totalBalance, 
                decimals: decimals, 
                rawAmount: totalRawAmount 
            };
        } catch (error) {
            console.error(`❌ Error getting token account info: ${error.message}`);
            return { balance: 0, decimals: 6, rawAmount: 0 };
        }
    }
    
    async getTokenBalance(tokenMintAddress) {
        const info = await this.getTokenAccountInfo(tokenMintAddress);
        return info.balance;
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
    
    async getJupiterQuote(inputMint, outputMint, amount, slippageBps = 300) {
        // Make sure amount is a string and represents the raw token amount
        const amountStr = amount.toString();
        const url = `${this.config.jupiter.api_url}/quote?inputMint=${inputMint}&outputMint=${outputMint}&amount=${amountStr}&slippageBps=${slippageBps}`;
        
        console.log(`🔍 Jupiter Quote URL: ${url}`);
        
        try {
            const response = await fetch(url);
            const responseText = await response.text();
            
            if (!response.ok) {
                console.error(`❌ Jupiter API Response: ${response.status} ${response.statusText}`);
                console.error(`❌ Response body: ${responseText}`);
                throw new Error(`Jupiter quote failed: ${response.status} ${response.statusText} - ${responseText}`);
            }
            
            return JSON.parse(responseText);
        } catch (error) {
            console.error(`❌ Jupiter quote error: ${error.message}`);
            throw error;
        }
    }
    
    async getJupiterSwapTransaction(quoteResponse) {
        const swapBody = {
            quoteResponse,
            userPublicKey: this.wallet.publicKey.toString(),
            wrapAndUnwrapSol: true,
            dynamicComputeUnitLimit: true,
            prioritizationFeeLamports: Math.max(this.config.trading.priority_fee_lamports || 10000, 50000),
        };
        
        console.log(`🔍 Swap request body: ${JSON.stringify(swapBody, null, 2)}`);
        
        try {
            const swapResponse = await fetch(`${this.config.jupiter.api_url}/swap`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(swapBody),
            });
            
            const responseText = await swapResponse.text();
            
            if (!swapResponse.ok) {
                console.error(`❌ Jupiter Swap Response: ${swapResponse.status} ${swapResponse.statusText}`);
                console.error(`❌ Response body: ${responseText}`);
                throw new Error(`Jupiter swap failed: ${swapResponse.status} ${swapResponse.statusText} - ${responseText}`);
            }
            
            return JSON.parse(responseText);
        } catch (error) {
            console.error(`❌ Jupiter swap error: ${error.message}`);
            throw error;
        }
    }
    
    async waitForConfirmation(signature) {
        console.log(`⏳ Waiting for confirmation of ${signature}...`);
        
        const startTime = Date.now();
        const timeout = 180000; // 3 minutes for bailout
        
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
    
    async getCurrentTokenPrice(tokenAddress, tokenInfo) {
        try {
            const SOL_MINT = 'So11111111111111111111111111111111111111112';
            
            if (tokenInfo.rawAmount === 0) {
                return null;
            }
            
            // Use raw amount for Jupiter quote
            const quote = await this.getJupiterQuote(tokenAddress, SOL_MINT, tokenInfo.rawAmount, 300);
            const solReceived = parseInt(quote.outAmount) / 1e9;
            const pricePerToken = tokenInfo.balance > 0 ? solReceived / tokenInfo.balance : 0;
            
            return { pricePerToken, solReceived, quote };
        } catch (error) {
            console.error(`❌ Error getting token price: ${error.message}`);
            return null;
        }
    }
    
    async displayCurrentPosition() {
        console.log('\n📊 === CURRENT POSITION ANALYSIS ===');
        
        const solBalance = await this.getSolBalance();
        console.log(`💰 SOL Balance: ${solBalance.toFixed(6)} SOL`);
        
        const tokens = Object.entries(this.config.tokens);
        let totalPositionValue = solBalance;
        
        for (const [tokenSymbol, tokenAddress] of tokens) {
            const tokenInfo = await this.getTokenAccountInfo(tokenAddress);
            
            if (tokenInfo.balance > 0) {
                console.log(`\n🪙 ${tokenSymbol} Balance: ${tokenInfo.balance.toLocaleString()}`);
                console.log(`🔢 Raw Amount: ${tokenInfo.rawAmount.toLocaleString()}`);
                console.log(`🎯 Decimals: ${tokenInfo.decimals}`);
                
                const priceData = await this.getCurrentTokenPrice(tokenAddress, tokenInfo);
                if (priceData) {
                    console.log(`💎 Current Value: ${priceData.solReceived.toFixed(6)} SOL`);
                    console.log(`📈 Price per token: ${priceData.pricePerToken.toFixed(10)} SOL`);
                    totalPositionValue += priceData.solReceived;
                } else {
                    console.log(`❌ Could not get current price`);
                }
            } else {
                console.log(`\n🪙 ${tokenSymbol}: No balance`);
            }
        }
        
        console.log(`\n💰 Total Position Value: ~${totalPositionValue.toFixed(6)} SOL`);
        console.log('=====================================\n');
        
        return { solBalance, tokens, totalPositionValue };
    }
    
    async executeSellTransaction(tokenAddress, tokenSymbol, tokenInfo, slippageBps = 300) {
        try {
            console.log(`\n🔄 Executing sell: ${tokenInfo.balance.toLocaleString()} ${tokenSymbol}`);
            console.log(`🔢 Raw amount: ${tokenInfo.rawAmount.toLocaleString()}`);
            console.log(`🎯 Decimals: ${tokenInfo.decimals}`);
            
            const SOL_MINT = 'So11111111111111111111111111111111111111112';
            
            if (tokenInfo.rawAmount === 0) {
                throw new Error('No tokens to sell (raw amount is 0)');
            }
            
            // Get fresh quote using raw amount
            console.log('📊 Getting Jupiter quote...');
            const quote = await this.getJupiterQuote(tokenAddress, SOL_MINT, tokenInfo.rawAmount, slippageBps);
            
            const expectedSol = parseInt(quote.outAmount) / 1e9;
            console.log(`📈 Quote: ${tokenInfo.balance.toLocaleString()} ${tokenSymbol} → ~${expectedSol.toFixed(6)} SOL`);
            
            // Create swap transaction
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
            
            // Wait for confirmation
            await this.waitForConfirmation(signature);
            
            console.log(`🎉 Sell completed successfully!`);
            
            return {
                success: true,
                signature,
                tokensSold: tokenInfo.balance,
                rawAmount: tokenInfo.rawAmount,
                expectedSol,
                timestamp: new Date().toISOString()
            };
            
        } catch (error) {
            console.error(`❌ Sell transaction failed: ${error.message}`);
            return {
                success: false,
                error: error.message,
                tokensSold: tokenInfo.balance,
                rawAmount: tokenInfo.rawAmount,
                timestamp: new Date().toISOString()
            };
        }
    }
    
    async logBailoutSale(results) {
        const logEntry = {
            timestamp: new Date().toISOString(),
            type: 'BAILOUT_SELL',
            wallet: this.wallet.publicKey.toString(),
            results: results,
            total_transactions: results.length,
            successful_sales: results.filter(r => r.success).length,
            failed_sales: results.filter(r => !r.success).length
        };
        
        let bailoutLog = [];
        const logFile = 'bailout_sales_log.json';
        
        if (fs.existsSync(logFile)) {
            bailoutLog = JSON.parse(fs.readFileSync(logFile, 'utf-8'));
        }
        
        bailoutLog.push(logEntry);
        fs.writeFileSync(logFile, JSON.stringify(bailoutLog, null, 2));
        
        console.log(`📝 Bailout sale logged to ${logFile}`);
    }
    
    async performBailout() {
        try {
            console.log('🚨 EMERGENCY BAILOUT SELL SCRIPT 🚨');
            console.log('====================================');
            
            // Display current position
            const positionData = await this.displayCurrentPosition();
            
            // Find tokens with balance
            const tokensWithBalance = [];
            for (const [tokenSymbol, tokenAddress] of positionData.tokens) {
                const tokenInfo = await this.getTokenAccountInfo(tokenAddress);
                if (tokenInfo.balance > 0 && tokenInfo.rawAmount > 0) {
                    tokensWithBalance.push({ 
                        symbol: tokenSymbol, 
                        address: tokenAddress, 
                        info: tokenInfo
                    });
                }
            }
            
            if (tokensWithBalance.length === 0) {
                console.log('✅ No tokens to sell - wallet only contains SOL');
                rl.close();
                return;
            }
            
            console.log(`🎯 Found ${tokensWithBalance.length} token(s) to sell:`);
            tokensWithBalance.forEach((token, index) => {
                console.log(`   ${index + 1}. ${token.symbol}: ${token.info.balance.toLocaleString()} (${token.info.rawAmount.toLocaleString()} raw)`);
            });
            
            // Confirmation prompts
            console.log('\n⚠️  WARNING: This will sell ALL your tokens immediately!');
            console.log('⚠️  This action cannot be undone!');
            
            const confirm1 = await question('\n❓ Are you sure you want to proceed? (type "YES" to continue): ');
            if (confirm1 !== 'YES') {
                console.log('❌ Bailout cancelled');
                rl.close();
                return;
            }
            
            const confirm2 = await question('\n❓ Final confirmation - sell everything NOW? (type "SELL ALL" to proceed): ');
            if (confirm2 !== 'SELL ALL') {
                console.log('❌ Bailout cancelled');
                rl.close();
                return;
            }
            
            // Ask about slippage tolerance
            console.log('\n📊 Slippage Settings:');
            console.log('   1. Conservative (3%) - Safer but might fail in volatile markets');
            console.log('   2. Aggressive (10%) - More likely to succeed but worse price');
            console.log('   3. Extreme (20%) - Emergency mode, accepts significant slippage');
            
            const slippageChoice = await question('\nSelect slippage tolerance (1-3, or Enter for Conservative): ');
            
            let slippageBps;
            switch(slippageChoice) {
                case '2': slippageBps = 1000; break; // 10%
                case '3': slippageBps = 2000; break; // 20%
                default: slippageBps = 300; break;   // 3%
            }
            
            console.log(`\n🚀 Starting bailout with ${slippageBps/100}% slippage tolerance...`);
            console.log('⏳ This may take several minutes...\n');
            
            // Execute sells
            const results = [];
            let totalSolReceived = 0;
            
            for (let i = 0; i < tokensWithBalance.length; i++) {
                const token = tokensWithBalance[i];
                console.log(`\n[${i + 1}/${tokensWithBalance.length}] Selling ${token.symbol}...`);
                
                const result = await this.executeSellTransaction(
                    token.address, 
                    token.symbol, 
                    token.info,
                    slippageBps
                );
                
                results.push({
                    ...result,
                    tokenSymbol: token.symbol,
                    tokenAddress: token.address
                });
                
                if (result.success) {
                    totalSolReceived += result.expectedSol;
                    console.log(`✅ Successfully sold ${token.symbol}`);
                } else {
                    console.log(`❌ Failed to sell ${token.symbol}: ${result.error}`);
                }
                
                // Small delay between transactions
                if (i < tokensWithBalance.length - 1) {
                    console.log('⏳ Waiting 5 seconds before next transaction...');
                    await new Promise(resolve => setTimeout(resolve, 5000));
                }
            }
            
            // Final summary
            console.log('\n🏁 === BAILOUT COMPLETE ===');
            console.log(`📊 Transactions: ${results.length}`);
            console.log(`✅ Successful: ${results.filter(r => r.success).length}`);
            console.log(`❌ Failed: ${results.filter(r => !r.success).length}`);
            console.log(`💰 Est. SOL received: ${totalSolReceived.toFixed(6)} SOL`);
            
            // Show final balances
            console.log('\n📈 Final wallet state:');
            const finalSolBalance = await this.getSolBalance();
            console.log(`💰 SOL Balance: ${finalSolBalance.toFixed(6)} SOL`);
            
            // Log the bailout
            await this.logBailoutSale(results);
            
            console.log('\n🎉 Bailout operation completed!');
            
        } catch (error) {
            console.error('❌ Bailout failed:', error);
        } finally {
            rl.close();
        }
    }
}

// Start the bailout process
if (require.main === module) {
    const bailout = new BailoutSeller();
    bailout.performBailout();
}

module.exports = BailoutSeller;