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

async function interactiveBuyOrder() {
    try {
        console.log('🤖 Manual Buy Order Creator');
        console.log('================================');
        
        // Load config to show available tokens
        const configData = fs.readFileSync('bot_config.json', 'utf-8');
        const config = JSON.parse(configData);
        
        console.log('\n📋 Available tokens:');
        const tokens = Object.entries(config.tokens);
        tokens.forEach(([symbol, address], index) => {
            console.log(`   ${index + 1}. ${symbol}: ${address}`);
        });
        
        // Get SOL amount
        const solAmountInput = await question('\n💰 Enter SOL amount to spend: ');
        const solAmount = parseFloat(solAmountInput);
        
        if (isNaN(solAmount) || solAmount <= 0) {
            console.log('❌ Invalid SOL amount');
            rl.close();
            return;
        }
        
        // Get token selection
        let tokenSymbol, tokenAddress;
        
        if (tokens.length === 1) {
            tokenSymbol = tokens[0][0];
            tokenAddress = tokens[0][1];
            console.log(`🎯 Using token: ${tokenSymbol}`);
        } else {
            const tokenChoice = await question('\n🪙 Select token number (or press Enter for first): ');
            const tokenIndex = tokenChoice ? parseInt(tokenChoice) - 1 : 0;
            
            if (tokenIndex < 0 || tokenIndex >= tokens.length) {
                console.log('❌ Invalid token selection');
                rl.close();
                return;
            }
            
            tokenSymbol = tokens[tokenIndex][0];
            tokenAddress = tokens[tokenIndex][1];
        }
        
        // Confirm the order
        console.log('\n📊 Order Summary:');
        console.log(`   💰 SOL Amount: ${solAmount}`);
        console.log(`   🪙 Token: ${tokenSymbol}`);
        console.log(`   📍 Address: ${tokenAddress}`);
        
        const confirm = await question('\n✅ Confirm order? (y/N): ');
        
        if (confirm.toLowerCase() !== 'y' && confirm.toLowerCase() !== 'yes') {
            console.log('❌ Order cancelled');
            rl.close();
            return;
        }
        
        // Create and insert the order
        const buyOrder = {
            command: 'BUY',
            token_symbol: tokenSymbol,
            token_address: tokenAddress,
            sol_amount: solAmount,
            timestamp: new Date().toISOString(),
            processed: false,
            source: 'manual_interactive'
        };
        
        // Load existing pending trades
        let pendingTrades = [];
        const pendingFile = 'pending_trades.json';
        
        if (fs.existsSync(pendingFile)) {
            pendingTrades = JSON.parse(fs.readFileSync(pendingFile, 'utf-8'));
        }
        
        pendingTrades.push(buyOrder);
        fs.writeFileSync(pendingFile, JSON.stringify(pendingTrades, null, 2));
        
        console.log('\n🎉 Buy order created successfully!');
        console.log(`📋 Queue position: ${pendingTrades.length}`);
        console.log('⏳ The bot will process this order shortly...');
        
        rl.close();
        
    } catch (error) {
        console.error('❌ Error:', error.message);
        rl.close();
    }
}

if (require.main === module) {
    interactiveBuyOrder();
}