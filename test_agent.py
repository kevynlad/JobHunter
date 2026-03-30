import asyncio
import os
import sys
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from src.bot.agent import CareerAgent

async def test():
    load_dotenv()
    print("Testing CareerAgent locally...")
    agent = CareerAgent(user_id=12345)
    
    # Send a message that should trigger a tool call
    print("Sending message: 'quais vagas você achou hoje?'")
    try:
        response = await agent.chat_async("quais vagas você achou hoje?")
        print("\n\n=== RESPONSE ===")
        print(response)
        
        print("\n\n=== HISTORY LENGTH ===")
        print(f"History length: {len(agent.history)}")
        for i, item in enumerate(agent.history):
            print(f"[{i}] {item.role}: {len(str(item))} chars")
            
    except Exception as e:
        print(f"FATAL ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test())
