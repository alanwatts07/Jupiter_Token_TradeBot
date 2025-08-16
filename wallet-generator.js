const { Keypair } = require('@solana/web3.js');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

class WalletGenerator {
  constructor() {
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });
  }

  async askQuestion(question) {
    return new Promise((resolve) => {
      this.rl.question(question, (answer) => {
        resolve(answer.trim());
      });
    });
  }

  ensureKeysDirectory() {
    const keysDir = './keys';
    if (!fs.existsSync(keysDir)) {
      fs.mkdirSync(keysDir, { recursive: true });
      console.log('📁 Created keys directory');
    }
    return keysDir;
  }

  loadBotConfig() {
    const configPath = './bot_config.json';
    let config = {};
    
    if (fs.existsSync(configPath)) {
      try {
        config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
        console.log('📖 Loaded existing bot_config.json');
      } catch (error) {
        console.log('⚠️  Error reading bot_config.json, will create new one');
      }
    } else {
      console.log('📝 bot_config.json not found, will create new one');
    }

    // Ensure all required sections exist
    if (!config.trading) {
      config.trading = {
        sol_amount_per_trade: 0.1,
        slippage_bps: 100,
        priority_fee_lamports: 100000,
        enabled: false  // Start disabled for safety
      };
    }

    if (!config.wallet) {
      config.wallet = {};
    }

    if (!config.tokens) {
      config.tokens = {
        "ANON": "FhvBDEr46meW6NHWHNeShDzvbXWabNzyT6uGinEgBAGS"
      };
    }

    if (!config.jupiter) {
      config.jupiter = {
        api_url: "https://quote-api.jup.ag/v6"
      };
    }

    return config;
  }

  saveBotConfig(config) {
    fs.writeFileSync('./bot_config.json', JSON.stringify(config, null, 2));
    console.log('✅ Updated bot_config.json');
  }

  generateWallet() {
    const keypair = Keypair.generate();
    const publicKey = keypair.publicKey.toString();
    const secretKey = Array.from(keypair.secretKey);
    
    console.log('\n🔐 Generated new wallet:');
    console.log(`   Public Key: ${publicKey}`);
    
    return {
      publicKey,
      secretKey,
      keypair
    };
  }

  saveKeypair(walletData, keysDir) {
    const filename = `${walletData.publicKey}.json`;
    const filepath = path.join(keysDir, filename);
    
    fs.writeFileSync(filepath, JSON.stringify(walletData.secretKey, null, 2));
    console.log(`💾 Saved keypair to: ${filepath}`);
    
    return filepath;
  }

  displayFundingInstructions(publicKey) {
    console.log('\n' + '='.repeat(80));
    console.log('💰 FUNDING INSTRUCTIONS');
    console.log('='.repeat(80));
    console.log(`\n🎯 Send SOL to this address: ${publicKey}`);
    console.log('\n📝 How to fund your wallet:');
    console.log('   1. Copy the address above');
    console.log('   2. Send SOL from your main wallet (Phantom, Solflare, etc.)');
    console.log('   3. Recommended: Start with 0.5-1.0 SOL for testing');
    console.log('   4. The bot will use the configured amount per trade');
    console.log('\n⚠️  IMPORTANT: Keep your private key safe!');
    console.log(`   📁 Keypair saved in: ./keys/${publicKey}.json`);
    console.log('   🚫 Never share this file or your private key!');
    console.log('\n' + '='.repeat(80));
  }

  displayConfigSummary(config) {
    console.log('\n📋 Current Bot Configuration:');
    console.log('=' .repeat(50));
    console.log(`💰 SOL per trade: ${config.trading.sol_amount_per_trade}`);
    console.log(`📊 Slippage: ${config.trading.slippage_bps / 100}%`);
    console.log(`⚡ Priority fee: ${config.trading.priority_fee_lamports} lamports`);
    console.log(`🚀 Trading enabled: ${config.trading.enabled}`);
    console.log(`🔑 Wallet keypair: ${config.wallet.private_key_path}`);
    console.log('=' .repeat(50));
  }

  async run() {
    console.log('🚀 Solana Wallet Generator for Trading Bot');
    console.log('=========================================\n');

    try {
      // Load or create bot config
      const config = this.loadBotConfig();
      
      // Check if wallet already exists
      if (config.wallet.private_key_path) {
        console.log(`⚠️  Existing wallet found: ${config.wallet.private_key_path}`);
        const overwrite = await this.askQuestion('Do you want to generate a new wallet? (yes/no): ');
        
        if (overwrite.toLowerCase() !== 'yes' && overwrite.toLowerCase() !== 'y') {
          console.log('✋ Keeping existing wallet configuration');
          this.displayConfigSummary(config);
          this.rl.close();
          return;
        }
      }

      // Ask for trading configuration
      console.log('\n🛠️  Trading Configuration:');
      
      const solAmount = await this.askQuestion(`SOL amount per trade [${config.trading.sol_amount_per_trade}]: `);
      if (solAmount && !isNaN(parseFloat(solAmount))) {
        config.trading.sol_amount_per_trade = parseFloat(solAmount);
      }

      const slippage = await this.askQuestion(`Slippage percentage [${config.trading.slippage_bps / 100}]: `);
      if (slippage && !isNaN(parseFloat(slippage))) {
        config.trading.slippage_bps = parseFloat(slippage) * 100;
      }

      // Generate new wallet
      console.log('\n🔐 Generating new wallet...');
      const keysDir = this.ensureKeysDirectory();
      const walletData = this.generateWallet();
      const keypairPath = this.saveKeypair(walletData, keysDir);

      // Update config with new wallet
      config.wallet.private_key_path = keypairPath;
      config.wallet.public_key = walletData.publicKey;

      // Ask if trading should be enabled
      const enableTrading = await this.askQuestion('\nEnable trading immediately? (yes/no) [no]: ');
      config.trading.enabled = (enableTrading.toLowerCase() === 'yes' || enableTrading.toLowerCase() === 'y');

      // Save updated config
      this.saveBotConfig(config);

      // Display summary
      this.displayConfigSummary(config);
      this.displayFundingInstructions(walletData.publicKey);

      if (!config.trading.enabled) {
        console.log('\n🛡️  Trading is DISABLED for safety.');
        console.log('   Edit bot_config.json and set "enabled": true when ready to trade.');
      }

      console.log('\n✅ Wallet generation complete!');
      console.log('🚀 You can now run your trading bot with: npm start');

    } catch (error) {
      console.error('\n❌ Error generating wallet:', error);
    } finally {
      this.rl.close();
    }
  }
}

// Run the wallet generator
if (require.main === module) {
  const generator = new WalletGenerator();
  generator.run();
}

module.exports = WalletGenerator;