import redis
import json
import os
import time
import logging
from typing import Set, List, Optional

logger = logging.getLogger(__name__)

class Cache:
    def __init__(self, url: str = "redis://localhost:6379"):
        self.redis_client = redis.from_url(url, decode_responses=True)
        self.opt_out_key = "opt_out_numbers"
        self.agents_key = "active_agents"

    def _ensure_connection(self):
        """Ensure Redis connection is available"""
        try:
            self.redis_client.ping()
            return True
        except redis.ConnectionError:
            logger.error("Redis connection failed")
            return False

    # Opt-out management methods
    def get_opt_out_numbers(self) -> Set[str]:
        """Get all opted-out phone numbers"""
        if not self._ensure_connection():
            return set()

        try:
            numbers = self.redis_client.smembers(self.opt_out_key)
            return set(numbers) if numbers else set()
        except Exception as e:
            logger.error(f"Error getting opt-out numbers: {e}")
            return set()

    def add_opt_out_number(self, phone: str) -> bool:
        """Add phone number to opt-out list"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            result = self.redis_client.sadd(self.opt_out_key, phone)
            # Persist to file as backup
            self._persist_opt_out_to_file()
            return result > 0
        except Exception as e:
            logger.error(f"Error adding opt-out number: {e}")
            return False

    def remove_opt_out_number(self, phone: str) -> bool:
        """Remove phone number from opt-out list"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            result = self.redis_client.srem(self.opt_out_key, phone)
            # Persist to file as backup
            self._persist_opt_out_to_file()
            return result > 0
        except Exception as e:
            logger.error(f"Error removing opt-out number: {e}")
            return False

    def is_opted_out(self, phone: str) -> bool:
        """Check if phone number is opted out"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            return self.redis_client.sismember(self.opt_out_key, phone)
        except Exception as e:
            logger.error(f"Error checking opt-out status: {e}")
            return False

    def _persist_opt_out_to_file(self):
        """Persist opt-out numbers to file as backup"""
        try:
            opt_out_file = "data/opt_out_numbers.txt"
            numbers = self.get_opt_out_numbers()
            with open(opt_out_file, 'w', encoding='utf-8') as f:
                for number in sorted(numbers):
                    f.write(f"{number}\n")
        except Exception as e:
            logger.error(f"Error persisting opt-out to file: {e}")

    def load_opt_out_from_file(self):
        """Load opt-out numbers from file into cache (for migration/initialization)"""
        try:
            opt_out_file = "data/opt_out_numbers.txt"
            if os.path.exists(opt_out_file):
                with open(opt_out_file, 'r', encoding='utf-8') as f:
                    numbers = set()
                    for line in f:
                        line = line.strip()
                        if line:
                            numbers.add(line)
                    # Load into Redis
                    if numbers:
                        self.redis_client.sadd(self.opt_out_key, *numbers)
        except Exception as e:
            logger.error(f"Error loading opt-out from file: {e}")

    # Agent management methods
    def get_active_agents(self) -> List[str]:
        """Get list of active agent phone numbers"""
        if not self._ensure_connection():
            return []

        try:
            # Get all agent keys
            agent_keys = self.redis_client.keys("agent:*")
            active_agents = []

            for key in agent_keys:
                # Check if agent session is still valid (not expired)
                if self.redis_client.exists(key):
                    phone = key.split(":", 1)[1]
                    active_agents.append(phone)

            return active_agents
        except Exception as e:
            logger.error(f"Error getting active agents: {e}")
            return []

    def agent_login(self, phone: str, ttl: int = 28800, email: Optional[str] = None) -> bool:
        """Log in an agent (phone number)"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            agent_key = f"agent:{phone}"
            # Store agent data with TTL
            agent_data = {
                "phone": phone,
                "login_time": int(time.time()),
                "status": "active"
            }
            if email:
                agent_data["email"] = email
            self.redis_client.setex(agent_key, ttl, json.dumps(agent_data))
            logger.info(f"Agent {phone} logged in with email {email}")
            return True
        except Exception as e:
            logger.error(f"Error logging in agent: {e}")
            return False

    def agent_logout(self, phone: str) -> bool:
        """Log out an agent"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            agent_key = f"agent:{phone}"
            result = self.redis_client.delete(agent_key)
            if result > 0:
                logger.info(f"Agent {phone} logged out")
            return result > 0
        except Exception as e:
            logger.error(f"Error logging out agent: {e}")
            return False

    def is_agent_active(self, phone: str) -> bool:
        """Check if agent is currently active/logged in"""
        if not phone:
            return False

        if not self._ensure_connection():
            return False

        try:
            agent_key = f"agent:{phone}"
            return self.redis_client.exists(agent_key)
        except Exception as e:
            logger.error(f"Error checking agent status: {e}")
            return False

    def get_agent_info(self, phone: str) -> Optional[dict]:
        """Get agent information"""
        if not phone:
            return None

        if not self._ensure_connection():
            return None

        try:
            agent_key = f"agent:{phone}"
            data = self.redis_client.get(agent_key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Error getting agent info: {e}")
            return None

    # Health check
    def health_check(self) -> bool:
        """Check if cache is healthy"""
        return self._ensure_connection()