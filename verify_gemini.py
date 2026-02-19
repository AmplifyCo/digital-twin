
import asyncio
import os
import sys

# Add src to path just in case, though we just need litellm
sys.path.insert(0, os.getcwd())

try:
    from litellm import acompletion
except ImportError:
    print("Please install litellm first: pip install litellm")
    sys.exit(1)

async def check_version():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in environment.")
        print("Run: export GEMINI_API_KEY=your_key_here")
        return

    print("Querying generic alias 'gemini/gemini-pro-latest'...")
    try:
        response = await acompletion(
            model="gemini/gemini-pro-latest",
            messages=[{
                "role": "user", 
                "content": "What is your exact model version? Are you Gemini 1.5, 2.0, or 3.1? What is your knowledge cutoff date?"
            }]
        )
        print("\n--- Model Response ---")
        print(response.choices[0].message.content)
        print("\n--- Metadata ---")
        print(f"Model ID returned: {response.model}")
        
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    asyncio.run(check_version())
