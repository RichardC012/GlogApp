# app.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import boto3
from mangum import Mangum
from contextlib import asynccontextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# Initialize FastAPI app
app = FastAPI(title="Serverless API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Specify your frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
async def get_db_pool():
    """
    Create a connection pool to PostgreSQL.
    Credentials are fetched from AWS Secrets Manager in production
    or environment variables in development.
    """
    if os.environ.get("AWS_EXECUTION_ENV"):
        # We're running in Lambda, get credentials from Secrets Manager
        secret_name = os.environ.get("DB_SECRET_NAME")
        region = os.environ.get("AWS_REGION", "us-east-1")
        
        client = boto3.client('secretsmanager', region_name=region)
        secret_value = client.get_secret_value(SecretId=secret_name)
        db_credentials = json.loads(secret_value['SecretString'])
        
        conninfo = (
            f"host={db_credentials['host']} "
            f"dbname={db_credentials['dbname']} "
            f"user={db_credentials['username']} "
            f"password={db_credentials['password']} "
            f"port={db_credentials.get('port', 5432)}"
        )
    else:
        # Local development
        host = os.environ.get("DB_HOST", "localhost")
        database = os.environ.get("DB_NAME", "postgres")
        user = os.environ.get("DB_USER", "postgres")
        password = os.environ.get("DB_PASSWORD", "postgres")
        port = os.environ.get("DB_PORT", "5432")
        
        conninfo = f"host={host} dbname={database} user={user} password={password} port={port}"
    
    return AsyncConnectionPool(conninfo=conninfo, min_size=1, max_size=10)

# Database dependency
@asynccontextmanager
async def get_db():
    """Get a database connection from the pool."""
    pool = app.state.db_pool
    async with pool.connection() as conn:
        # Use dict_row to return results as dictionaries
        conn.row_factory = dict_row
        yield conn

# Pydantic models
class ItemBase(BaseModel):
    name: str
    description: Optional[str] = None

class ItemCreate(ItemBase):
    pass

class Item(ItemBase):
    id: int

# API Routes
@app.get("/")
async def root():
    return {"message": "Welcome to the Serverless API"}

@app.get("/items/", response_model=List[Item])
async def read_items():
    """Get all items."""
    async with get_db() as db:
        async with db.cursor() as cur:
            await cur.execute("SELECT id, name, description FROM items")
            rows = await cur.fetchall()
    return rows

@app.get("/items/{item_id}", response_model=Item)
async def read_item(item_id: int):
    """Get a specific item by ID."""
    async with get_db() as db:
        async with db.cursor() as cur:
            await cur.execute(
                "SELECT id, name, description FROM items WHERE id = %s",
                (item_id,)
            )
            row = await cur.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return row

@app.post("/items/", response_model=Item)
async def create_item(item: ItemCreate):
    """Create a new item."""
    async with get_db() as db:
        async with db.cursor() as cur:
            await cur.execute(
                "INSERT INTO items (name, description) VALUES (%s, %s) RETURNING id, name, description",
                (item.name, item.description)
            )
            row = await cur.fetchone()
            await db.commit()
    
    return row

@app.put("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, item: ItemCreate):
    """Update an item."""
    async with get_db() as db:
        async with db.cursor() as cur:
            await cur.execute(
                "UPDATE items SET name = %s, description = %s WHERE id = %s RETURNING id, name, description",
                (item.name, item.description, item_id)
            )
            row = await cur.fetchone()
            await db.commit()
    
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return row

@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    """Delete an item."""
    async with get_db() as db:
        async with db.cursor() as cur:
            await cur.execute("DELETE FROM items WHERE id = %s", (item_id,))
            row_count = cur.rowcount
            await db.commit()
    
    if row_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Item deleted successfully"}

# Startup and shutdown events
@app.on_event("startup")
async def startup():
    """Initialize database connection pool on startup."""
    app.state.db_pool = await get_db_pool()

@app.on_event("shutdown")
async def shutdown():
    """Close database connection pool on shutdown."""
    await app.state.db_pool.close()

# Lambda handler
handler = Mangum(app)