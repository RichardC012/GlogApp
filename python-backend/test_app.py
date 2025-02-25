# test_app.py
import pytest
from httpx import AsyncClient
from app import app

@pytest.mark.asyncio
async def test_read_main():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Welcome to the Serverless API"}

@pytest.mark.asyncio
async def test_create_item():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/items/",
            json={"name": "Test Item", "description": "This is a test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["name"] == "Test Item"
        assert data["description"] == "This is a test"