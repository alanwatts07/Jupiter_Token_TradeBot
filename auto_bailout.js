
const BailoutSeller = require('./bailout.js');

async function autoSell() {
    try {
        const bailout = new BailoutSeller();
        
        // Get current position
        console.log('🚨 EMERGENCY BAILOUT INITIATED FROM DISCORD BOT');
        console.log('====================================');
        
        const positionData = await bailout.displayCurrentPosition();
        
        // Find tokens with balance
        const tokensWithBalance = [];
        for (const [tokenSymbol, tokenAddress] of positionData.tokens) {
            const balance = await bailout.getTokenBalance(tokenAddress);
            if (balance > 0) {
                tokensWithBalance.push({ symbol: tokenSymbol, address: tokenAddress, balance });
            }
        }
        
        if (tokensWithBalance.length === 0) {
            console.log('✅ No tokens to sell - wallet only contains SOL');
            console.log('\n===BAILOUT_SUMMARY===');
            console.log(JSON.stringify({
                success: true,
                totalTransactions: 0,
                successfulSales: 0,
                failedSales: 0,
                totalSolReceived: 0,
                message: 'No tokens to sell'
            }));
            process.exit(0);
        }
        
        console.log(`🎯 Found ${tokensWithBalance.length} token(s) to sell:`);
        tokensWithBalance.forEach((token, index) => {
            console.log(`   ${index + 1}. ${token.symbol}: ${token.balance.toLocaleString()}`);
        });
        
        // Auto-execute with 10% slippage for reliability
        const slippageBps = 1000; // 10%
        console.log(`\n🚀 Starting auto-bailout with ${slippageBps/100}% slippage tolerance...`);
        
        // Execute sells
        const results = [];
        let totalSolReceived = 0;
        
        for (let i = 0; i < tokensWithBalance.length; i++) {
            const token = tokensWithBalance[i];
            console.log(`\n[${i + 1}/${tokensWithBalance.length}] Selling ${token.symbol}...`);
            
            const result = await bailout.executeSellTransaction(
                token.address, 
                token.symbol, 
                token.balance,
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
        
        // Log the bailout
        await bailout.logBailoutSale(results);
        
        console.log('\n🎉 Auto-bailout operation completed!');
        
        // Output summary as JSON for the bot to parse
        console.log('\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({
            success: true,
            totalTransactions: results.length,
            successfulSales: results.filter(r => r.success).length,
            failedSales: results.filter(r => !r.success).length,
            totalSolReceived: totalSolReceived,
            results: results
        }));
        
    } catch (error) {
        console.error('❌ Auto-bailout failed:', error);
        console.log('\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({
            success: false,
            error: error.message
        }));
    }
}

autoSell();
