# jupiter_main.py - Tmux Process Manager for Jupiter Trading Bot System (Safe Startup Edition)
#
# This script manages the startup and monitoring of the full 4-part Jupiter trading system.
# NEW: It now checks if a process is already running and will NOT restart it.
#      It only starts processes that are not currently active.
#
# 1. jupiter_tracker.py (price data collection and analysis)
# 2. app_anon.py (dashboard and signal generation)
# 3. trade_bot_anon.py (Discord alerts and trade triggering)
# 4. executor.js (Jupiter trade execution & wallet management)

import subprocess
import time
import os
import sys
import signal
from datetime import datetime

# --- Configuration ---
TRACKER_SCRIPT = "jupiter_tracker.py"
DASHBOARD_SCRIPT = "app_anon.py"
SIGNAL_BOT_SCRIPT = "trade_bot_anon.py"
EXECUTOR_SCRIPT = "executor.js"

CHECK_INTERVAL = 10  # Check process health every 10 seconds
STARTUP_DELAY = 5    # Wait 5 seconds between starting each process

# Tmux session names
TMUX_SESSIONS = {
    "Jupiter Tracker": "jupiter_tracker",
    "Dashboard": "dashboard_anon",
    "Signal Bot": "signal_bot_anon",
    "Jupiter Executor": "jupiter_executor"
}

class JupiterTmuxManager:
    def __init__(self):
        self.sessions = {}
        self.running = True
        
    def log(self, message):
        """Print timestamped log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        
    def check_tmux_installed(self):
        """Check if tmux is installed"""
        try:
            result = subprocess.run(['tmux', '-V'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"✅ Tmux found: {result.stdout.strip()}")
                return True
            return False
        except FileNotFoundError:
            self.log("❌ Tmux not installed! Please install tmux to use this manager.")
            return False
    
    def check_node_installed(self):
        """Check if Node.js is installed"""
        try:
            result = subprocess.run(['node', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"✅ Node.js found: {result.stdout.strip()}")
                return True
            return False
        except FileNotFoundError:
            self.log("❌ Node.js not installed! Please install Node.js to run the Jupiter executor.")
            return False
            
    def tmux_session_exists(self, session_name):
        """Check if a tmux session exists"""
        result = subprocess.run(['tmux', 'has-session', '-t', session_name], capture_output=True)
        return result.returncode == 0
            
    def kill_tmux_session(self, session_name):
        """Kill a tmux session if it exists"""
        if self.tmux_session_exists(session_name):
            subprocess.run(['tmux', 'kill-session', '-t', session_name], capture_output=True)
            self.log(f"🗑️  Killed tmux session: {session_name}")
        return True
        
    def start_python_process(self, script_name, process_name, session_name):
        """Start a Python process in a new tmux session"""
        try:
            if not os.path.exists(script_name):
                self.log(f"❌ ERROR: {script_name} not found!")
                return False
                
            self.log(f"🐍 Starting {process_name} (Python) in tmux session '{session_name}'...")
            
            cmd = ['tmux', 'new-session', '-d', '-s', session_name, sys.executable, script_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.sessions[process_name] = session_name
                self.log(f"✅ {process_name} started successfully")
                self.log(f"   💡 To view: tmux attach -t {session_name}")
                return True
            else:
                self.log(f"❌ ERROR starting {process_name}: {result.stderr}")
                return False
                
        except Exception as e:
            self.log(f"❌ ERROR starting {process_name}: {e}")
            return False
    
    def start_node_process(self, script_name, process_name, session_name):
        """Start a Node.js process in a new tmux session"""
        try:
            if not os.path.exists(script_name):
                self.log(f"❌ ERROR: {script_name} not found!")
                return False
                
            self.log(f"⚡ Starting {process_name} (Node.js) in tmux session '{session_name}'...")
            
            cmd = ['tmux', 'new-session', '-d', '-s', session_name, 'node', script_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.sessions[process_name] = session_name
                self.log(f"✅ {process_name} started successfully")
                self.log(f"   💡 To view: tmux attach -t {session_name}")
                return True
            else:
                self.log(f"❌ ERROR starting {process_name}: {result.stderr}")
                return False
                
        except Exception as e:
            self.log(f"❌ ERROR starting {process_name}: {e}")
            return False
            
    def stop_all_processes(self):
        """Stop all managed processes by killing their tmux sessions"""
        self.log("🛑 Stopping all managed tmux sessions...")
        for process_name, session_name in TMUX_SESSIONS.items():
            self.kill_tmux_session(session_name)
            self.log(f"   - Stopped {process_name} (session: {session_name})")
        self.sessions.clear()

    def start_all_processes(self):
        """Start all processes in correct order, skipping any that are already running."""
        self.log("🚀 Verifying Jupiter Trading Bot System in Tmux...")
        self.log("=" * 70)
        
        processes = [
            (TRACKER_SCRIPT, "Jupiter Tracker", TMUX_SESSIONS["Jupiter Tracker"], "python"),
            (DASHBOARD_SCRIPT, "Dashboard", TMUX_SESSIONS["Dashboard"], "python"),
            (SIGNAL_BOT_SCRIPT, "Signal Bot", TMUX_SESSIONS["Signal Bot"], "python"),
            (EXECUTOR_SCRIPT, "Jupiter Executor", TMUX_SESSIONS["Jupiter Executor"], "node")
        ]
        
        for script, process_name, session_name, runtime in processes:
            # First, check if the session already exists
            if self.tmux_session_exists(session_name):
                self.log(f"👍 {process_name} is already running in session '{session_name}'. Skipping.")
                self.sessions[process_name] = session_name # Add to monitor list
            else:
                # If it doesn't exist, start it
                if runtime == "python":
                    success = self.start_python_process(script, process_name, session_name)
                else:  # node
                    success = self.start_node_process(script, process_name, session_name)
                    
                if success:
                    self.log(f"⏳ Waiting {STARTUP_DELAY} seconds for {process_name} to initialize...")
                    time.sleep(STARTUP_DELAY)
                else:
                    self.log(f"❌ Failed to start {process_name}. Aborting system check.")
                    return False
                
        self.log("🎉 All required processes are running successfully!")
        self.log("=" * 70)
        return True
        
    def monitor_processes(self):
        """Monitor all processes and restart if needed"""
        self.log("👀 Monitoring tmux sessions...")
        
        while self.running:
            try:
                processes_info = [
                    ("Jupiter Tracker", TRACKER_SCRIPT, TMUX_SESSIONS["Jupiter Tracker"], "python"),
                    ("Dashboard", DASHBOARD_SCRIPT, TMUX_SESSIONS["Dashboard"], "python"),
                    ("Signal Bot", SIGNAL_BOT_SCRIPT, TMUX_SESSIONS["Signal Bot"], "python"),
                    ("Jupiter Executor", EXECUTOR_SCRIPT, TMUX_SESSIONS["Jupiter Executor"], "node")
                ]
                
                for process_name, script, session, runtime in processes_info:
                    if session not in self.sessions.values():
                         self.sessions[process_name] = session

                    if not self.tmux_session_exists(session):
                        self.log(f"⚠️  {process_name} is not running! Attempting restart...")
                        if runtime == "python":
                            self.start_python_process(script, process_name, session)
                        else:  # node
                            self.start_node_process(script, process_name, session)
                
                time.sleep(CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                self.log("🛑 Keyboard interrupt received...")
                break
            except Exception as e:
                self.log(f"❌ Error in monitoring loop: {e}")
                time.sleep(CHECK_INTERVAL)
                
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.log(f"📡 Received signal {signum}")
        self.running = False
        
    def show_status(self):
        """Show current system status"""
        self.log("\n📊 JUPITER TRADING SYSTEM STATUS:")
        self.log("-" * 70)
        
        processes = [
            ("Jupiter Tracker", "🔄 Price data collection & analysis", "python"),
            ("Dashboard", "📈 Signal generation & Fibonacci analysis", "python"),
            ("Signal Bot", "🔔 Discord alerts & trade triggering", "python"),
            ("Jupiter Executor", "⚡ DEX trade execution & wallet analytics", "node")
        ]
        
        for process_name, description, runtime in processes:
            session_name = TMUX_SESSIONS[process_name]
            runtime_emoji = "🐍" if runtime == "python" else "⚡"
            if self.tmux_session_exists(session_name):
                self.log(f"✅ {process_name:<16} {runtime_emoji} (tmux: {session_name:<16}) - {description}")
                self.sessions[process_name] = session_name # Ensure it's in our list
            else:
                self.log(f"❌ {process_name:<16} {runtime_emoji} (STOPPED) - {description}")
                
        self.log("-" * 70)
        self.log("🎯 Jupiter system is running! Press Ctrl+C to stop this manager (won't stop tmux sessions).")
        self.log("💡 To stop everything, run `python3 jupiter_main.py stop`")
        self.log(f"👀 Monitoring health every {CHECK_INTERVAL} seconds...")
        self.log("")
        
        self.log("💡 TMUX COMMANDS:")
        self.log("   tmux list-sessions")
        for process_name, session_name in TMUX_SESSIONS.items():
            self.log(f"   tmux attach -t {session_name:<18} - View {process_name} output")
        self.log("   Ctrl+B then D                        - Detach from a tmux session")
        self.log("")
        
        self.log("🌐 ACCESS POINTS:")
        self.log("   Dashboard: http://localhost:8051     - Live charts & signals")
        self.log("   Discord:   Check your configured bot - Alerts & notifications")
        self.log("")
        
        self.log("📁 KEY FILES:")
        self.log("   bot_config.json                      - Trading configuration")
        self.log("   wallet_statistics.json               - Live wallet analytics")
        self.log("   jupiter_trade_log.json               - Complete trade history")
        self.log("   pending_trades.json                  - Queued trades")
        self.log("")
        
    def check_config_files(self):
        """Check if required configuration files exist"""
        required_files = [
            ("config.json", "Discord bot configuration"),
            ("bot_config.json", "Trading bot configuration")
        ]
        
        missing_files = []
        for filename, description in required_files:
            if not os.path.exists(filename):
                missing_files.append((filename, description))
        
        if missing_files:
            self.log("⚠️  WARNING: Missing configuration files:")
            for filename, description in missing_files:
                self.log(f"   ❌ {filename} - {description}")
            self.log("")
            self.log("📖 Please refer to the README.md for configuration setup.")
            return False
        
        self.log("✅ All required configuration files found.")
        return True
        
    def run(self):
        """Main run function"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            if not self.check_tmux_installed(): return
            if not self.check_node_installed(): return
            if not self.check_config_files(): return
            if not self.start_all_processes(): return
            self.show_status()
            self.monitor_processes()
        except Exception as e:
            self.log(f"❌ Critical error in run loop: {e}")
        finally:
            self.log("👋 Manager stopped. Tmux sessions are still running in the background.")

def main():
    """Main entry point with command-line arguments for start/stop"""
    print("🤖 Jupiter Trading Bot System Manager (Tmux Edition)")
    print("=" * 70)

    manager = JupiterTmuxManager()

    if len(sys.argv) > 1 and sys.argv[1] == 'stop':
        manager.stop_all_processes()
        print("👋 Jupiter system shutdown complete.")
        return

    # Check if all script files exist before starting
    python_scripts = [TRACKER_SCRIPT, DASHBOARD_SCRIPT, SIGNAL_BOT_SCRIPT]
    node_scripts = [EXECUTOR_SCRIPT]
    
    missing_scripts = []
    for script in python_scripts + node_scripts:
        if not os.path.exists(script):
            missing_scripts.append(script)
    
    if missing_scripts:
        print("❌ Missing script files:")
        for script in missing_scripts:
            print(f"   - {script}")
        print("\n📖 Please ensure all Jupiter trading bot files are present.")
        return
        
    print("✅ All script files found.")
    
    # Check if package.json exists for Node.js dependencies
    if not os.path.exists("package.json"):
        print("⚠️  WARNING: package.json not found. Run 'npm install' to install Node.js dependencies.")
    
    manager.run()

if __name__ == "__main__":
    main()