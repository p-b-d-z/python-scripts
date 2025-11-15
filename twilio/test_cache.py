#!/usr/bin/env python3
"""
Simple test script to verify cache functionality
"""
import sys
import os

# Add current directory to path so we can import cache
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cache import Cache

def test_cache():
    print("Testing Valkey cache functionality...")

    # Initialize cache with local Redis (for testing)
    cache = Cache("redis://localhost:6379")

    # Test health check
    if not cache.health_check():
        print("❌ Cache health check failed - Redis not running")
        return False

    print("✅ Cache connection successful")

    # Test opt-out functionality
    test_phone = "+1234567890"

    # Add to opt-out
    if cache.add_opt_out_number(test_phone):
        print("✅ Added number to opt-out list")
    else:
        print("❌ Failed to add number to opt-out list")
        return False

    # Check if opted out
    if cache.is_opted_out(test_phone):
        print("✅ Number correctly identified as opted out")
    else:
        print("❌ Number not identified as opted out")
        return False

    # Remove from opt-out
    if cache.remove_opt_out_number(test_phone):
        print("✅ Removed number from opt-out list")
    else:
        print("❌ Failed to remove number from opt-out list")
        return False

    # Verify removed
    if not cache.is_opted_out(test_phone):
        print("✅ Number correctly identified as not opted out")
    else:
        print("❌ Number still identified as opted out")
        return False

    # Test agent functionality
    if cache.agent_login(test_phone):
        print("✅ Agent login successful")
    else:
        print("❌ Agent login failed")
        return False

    # Check active agents
    active_agents = cache.get_active_agents()
    if test_phone in active_agents:
        print("✅ Agent correctly identified as active")
    else:
        print("❌ Agent not identified as active")
        return False

    # Logout agent
    if cache.agent_logout(test_phone):
        print("✅ Agent logout successful")
    else:
        print("❌ Agent logout failed")
        return False

    # Verify logged out
    active_agents = cache.get_active_agents()
    if test_phone not in active_agents:
        print("✅ Agent correctly identified as inactive")
    else:
        print("❌ Agent still identified as active")
        return False

    print("🎉 All cache tests passed!")
    return True

if __name__ == "__main__":
    success = test_cache()
    sys.exit(0 if success else 1)