"""Authentication for telemetry node"""

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


class TokenAuth:
    def __init__(self, token_file: str = ".node_token"):
        self.token_file = Path(token_file)
        self.token = self._load_or_create_token()
        self.bearer = HTTPBearer(auto_error=False)
    
    def _load_or_create_token(self) -> str:
        """Load existing token or create new one"""
        # Check environment variable first
        token = os.environ.get("HAPA_TELEMETRY_TOKEN")
        if token:
            return token
        
        # Check token file
        if self.token_file.exists():
            token = self.token_file.read_text().strip()
            if token:
                return token
        
        # Generate new token
        token = secrets.token_urlsafe(32)
        self.token_file.write_text(token)
        print(f"Generated new token and saved to {self.token_file}")
        return token
    
    async def verify_token(
        self, 
        credentials: Optional[HTTPAuthorizationCredentials] = Security(HTTPBearer(auto_error=False))
    ) -> bool:
        """Verify bearer token"""
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if credentials.credentials != self.token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return True
    
    def get_token(self) -> str:
        """Get the current token"""
        return self.token
