from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

_WRITE_UOW_KEY = "finorch_write_uow"


@contextmanager
def write_transaction(session: Session, *, immediate: bool = False) -> Iterator[None]:
    """Own one write transaction, or join the explicit application write unit of work.

    SQLAlchemy starts a transaction for reads. A read-only autobegun transaction is
    closed before this function opens the write transaction so the business write
    starts from a fresh snapshot. Callers with pending writes must establish an
    explicit ``write_transaction`` first.
    """
    if session.info.get(_WRITE_UOW_KEY):
        yield
        return

    if session.in_transaction():
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("Pending writes require an explicit write transaction.")
        session.commit()

    with session.begin():
        previous = session.info.get(_WRITE_UOW_KEY)
        session.info[_WRITE_UOW_KEY] = True
        try:
            if immediate and session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            yield
        finally:
            if previous is None:
                session.info.pop(_WRITE_UOW_KEY, None)
            else:
                session.info[_WRITE_UOW_KEY] = previous
