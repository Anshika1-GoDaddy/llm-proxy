import requests
import json
import os
import sys

BASE_URL = os.environ.get("PROXY_URL", "http://localhost:8000")
API_KEY = os.environ.get("PROXY_API_KEY", "sk-my-proxy-key")


def test_health():
    """Test the health endpoint"""
    response = requests.get(f"{BASE_URL}/health")
    print(f"\n✅ Health check: {response.status_code}")
    print(response.json())


def test_chat_completions(message="Hello, how are you?"):
    """Test the chat completions endpoint"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": "gpt-4o",  # or whatever model is available
        "messages": [
            {"role": "user", "content": message}
        ],
        "stream": False
    }
    
    print(f"\n⏳ Testing chat completions with message: '{message}'")
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        headers=headers,
        json=data
    )
    
    print(f"📊 Status code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print("✅ Chat completions test successful")
        return result
    else:
        print(f"❌ Error: {response.text}")
        return None


def test_responses(message="Tell me a quick joke"):
    """Test the responses endpoint used by Agent Zero"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": "gpt-4o",  # or whatever model is available
        "input": message
    }
    
    print(f"\n⏳ Testing responses endpoint with message: '{message}'")
    response = requests.post(
        f"{BASE_URL}/v1/responses",
        headers=headers,
        json=data
    )
    
    print(f"📊 Status code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print("✅ Responses test successful")
        print(f"Response type: {result.get('type', 'MISSING')}")
        
        # Check if the type field exists (which was missing before)
        if "type" not in result:
            print("⚠️ Warning: 'type' field is still missing from the response!")
        
        # Get the actual response content
        try:
            content = result["output"][0]["content"][0]["text"]
            print(f"📝 Content preview: {content[:100]}...")
        except (KeyError, IndexError):
            print("❌ Could not extract content from response")
            
        return result
    else:
        print(f"❌ Error: {response.text}")
        return None


if __name__ == "__main__":
    try:
        test_health()
        
        if len(sys.argv) > 1:
            message = sys.argv[1]
            # Run both tests with the provided message
