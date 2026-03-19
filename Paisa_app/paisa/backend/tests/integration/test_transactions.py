"""
tests/integration/test_transactions.py
Integration tests for the transactions API.
Spins up test DB (SQLite in-memory for speed), uses httpx AsyncClient.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.database import get_db
from app.models.transaction import Base, User
from app.middleware.auth import get_current_user
from app.config import settings
import uuid
from datetime import datetime

# ─── Test DB setup ────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

TEST_USER = User(
    id=uuid.uuid4(),
    phone="9999999999",
    display_name="Test User",
    is_active=True,
)


async def override_get_db():
    async with TestSession() as session:
        yield session


async def override_get_current_user():
    return TEST_USER


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ─── Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_transaction(client):
    payload = {
        "client_id": str(uuid.uuid4()),
        "amount_paise": 50_000,
        "txn_type": "debit",
        "txn_date": datetime.utcnow().isoformat(),
        "description": "Swiggy order",
        "source": "manual",
    }
    resp = await client.post("/api/v1/transactions", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount_paise"] == 50_000
    assert data["amount_rupees"] == 500.0
    assert data["txn_type"] == "debit"


@pytest.mark.asyncio
async def test_idempotent_create(client):
    """Same client_id twice → second returns same transaction, not duplicate."""
    client_id = str(uuid.uuid4())
    payload = {
        "client_id": client_id,
        "amount_paise": 10_000,
        "txn_type": "debit",
        "txn_date": datetime.utcnow().isoformat(),
        "description": "Coffee",
        "source": "manual",
    }
    r1 = await client.post("/api/v1/transactions", json=payload)
    r2 = await client.post("/api/v1/transactions", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]  # same transaction returned


@pytest.mark.asyncio
async def test_list_transactions_cursor_pagination(client):
    # Create 5 transactions
    for i in range(5):
        await client.post("/api/v1/transactions", json={
            "client_id": str(uuid.uuid4()),
            "amount_paise": (i + 1) * 10_000,
            "txn_type": "debit",
            "txn_date": datetime.utcnow().isoformat(),
            "description": f"Transaction {i}",
            "source": "manual",
        })

    # Page 1 (limit=3)
    r1 = await client.get("/api/v1/transactions?limit=3")
    assert r1.status_code == 200
    d1 = r1.json()
    assert len(d1["items"]) == 3
    assert d1["next_cursor"] is not None

    # Page 2
    r2 = await client.get(f"/api/v1/transactions?limit=3&cursor={d1['next_cursor']}")
    d2 = r2.json()
    assert len(d2["items"]) == 2
    assert d2["next_cursor"] is None

    # No overlap
    ids1 = {t["id"] for t in d1["items"]}
    ids2 = {t["id"] for t in d2["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_batch_create_partial_failure(client):
    client_id = str(uuid.uuid4())
    # First request — create
    await client.post("/api/v1/transactions", json={
        "client_id": client_id,
        "amount_paise": 10_000,
        "txn_type": "debit",
        "txn_date": datetime.utcnow().isoformat(),
        "description": "Existing",
        "source": "manual",
    })

    # Batch with one duplicate and one new
    resp = await client.post("/api/v1/transactions/batch", json={
        "transactions": [
            {
                "client_id": client_id,     # duplicate
                "amount_paise": 10_000,
                "txn_type": "debit",
                "txn_date": datetime.utcnow().isoformat(),
                "description": "Duplicate",
                "source": "manual",
            },
            {
                "client_id": str(uuid.uuid4()),  # new
                "amount_paise": 20_000,
                "txn_type": "credit",
                "txn_date": datetime.utcnow().isoformat(),
                "description": "Salary",
                "source": "manual",
            },
        ]
    })
    assert resp.status_code == 207
    data = resp.json()
    assert data["created_count"] == 1
    assert data["duplicate_count"] == 1
    statuses = {r["client_id"]: r["status"] for r in data["results"]}
    assert statuses[client_id] == "duplicate"


@pytest.mark.asyncio
async def test_soft_delete(client):
    r = await client.post("/api/v1/transactions", json={
        "client_id": str(uuid.uuid4()),
        "amount_paise": 5_000,
        "txn_type": "debit",
        "txn_date": datetime.utcnow().isoformat(),
        "description": "To delete",
        "source": "manual",
    })
    txn_id = r.json()["id"]

    del_r = await client.delete(f"/api/v1/transactions/{txn_id}")
    assert del_r.status_code == 204

    # Should not appear in list
    list_r = await client.get("/api/v1/transactions")
    ids = [t["id"] for t in list_r.json()["items"]]
    assert txn_id not in ids
