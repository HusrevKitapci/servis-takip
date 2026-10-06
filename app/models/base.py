"""
Veritabanı modellerinin ortak temel sınıfı.

Bütün tablo modelleri bu sınıftan türeyecek.
SQLAlchemy, bu modellerin tablo tanımlarını Base.metadata içinde toplayacak.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Uygulamadaki bütün SQLAlchemy tablo modellerinin ortak tabanı."""