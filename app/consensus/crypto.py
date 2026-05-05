"""
Cryptographic utilities for PBFT consensus.

Provides message signing and verification to ensure Byzantine fault tolerance.
Each agent signs its messages so that faulty agents cannot impersonate others.

Author: Millicent Mufambi (H240624A)
"""

import hashlib
import hmac
import json
from typing import Optional
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature
import base64


class CryptoProvider:
    """
    Handles cryptographic operations for PBFT.

    For simplicity, uses HMAC with shared secrets in development.
    Can be upgraded to asymmetric signatures (RSA/ECDSA) for production.
    """

    def __init__(self, agent_id: str, secret_key: Optional[str] = None):
        self.agent_id = agent_id
        self.secret_key = (secret_key or f"dev-secret-{agent_id}").encode()

        # For production: generate/load asymmetric keys
        self._private_key = None
        self._public_key = None

    def sign_message(self, message_dict: dict) -> str:
        """
        Sign a message and return the signature.

        Args:
            message_dict: Dictionary containing the message data

        Returns:
            Base64-encoded signature string
        """
        # Remove existing signature if present
        message_copy = {k: v for k, v in message_dict.items() if k != "signature"}

        # Canonical JSON representation
        canonical = json.dumps(message_copy, sort_keys=True, default=str)

        # HMAC signature
        signature = hmac.new(
            self.secret_key,
            canonical.encode(),
            hashlib.sha256
        ).digest()

        return base64.b64encode(signature).decode()

    def verify_signature(
        self,
        message_dict: dict,
        signature: str,
        sender_id: str
    ) -> bool:
        """
        Verify a message signature.

        Args:
            message_dict: The message data
            signature: The signature to verify
            sender_id: ID of the agent that signed the message

        Returns:
            True if signature is valid, False otherwise
        """
        try:
            # In production, use sender's public key
            # For development, reconstruct secret from sender_id
            sender_secret = f"dev-secret-{sender_id}".encode()

            message_copy = {k: v for k, v in message_dict.items() if k != "signature"}
            canonical = json.dumps(message_copy, sort_keys=True, default=str)

            expected = hmac.new(
                sender_secret,
                canonical.encode(),
                hashlib.sha256
            ).digest()

            provided = base64.b64decode(signature)

            return hmac.compare_digest(expected, provided)
        except Exception:
            return False

    def compute_digest(self, data: dict) -> str:
        """Compute SHA-256 digest of data."""
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


class KeyManager:
    """
    Manages cryptographic keys for all agents.

    In a production system, this would:
    - Generate and store agent key pairs
    - Distribute public keys
    - Handle key rotation
    """

    def __init__(self):
        self._keys: dict[str, CryptoProvider] = {}

    def get_provider(self, agent_id: str) -> CryptoProvider:
        """Get or create a crypto provider for an agent."""
        if agent_id not in self._keys:
            self._keys[agent_id] = CryptoProvider(agent_id)
        return self._keys[agent_id]

    def register_agent(self, agent_id: str, secret_key: Optional[str] = None):
        """Register an agent with its cryptographic credentials."""
        self._keys[agent_id] = CryptoProvider(agent_id, secret_key)


# Global key manager instance
key_manager = KeyManager()
