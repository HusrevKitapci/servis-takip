"""
Kimlik doğrulama işlemlerinin yanıt modelleri.
"""

from typing import Literal

from pydantic import BaseModel


class TokenRead(BaseModel):
    """Başarılı giriş işleminde istemciye verilen erişim tokenı."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"