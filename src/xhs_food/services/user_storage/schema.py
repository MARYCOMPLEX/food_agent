# -*- coding: utf-8 -*-
"""SQL schema definitions for user storage tables."""

# Enable required extensions first
ENABLE_EXTENSIONS_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(255) UNIQUE,
    name VARCHAR(100) DEFAULT 'Guest',
    username VARCHAR(50) UNIQUE,
    email VARCHAR(255),
    avatar TEXT,
    location VARCHAR(100),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_FAVORITES_TABLE = """
CREATE TABLE IF NOT EXISTS favorites (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL,
    UNIQUE(user_id, restaurant_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_restaurant ON favorites(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_favorites_deleted ON favorites(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID UNIQUE,
    query TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'loading',
    results_count INTEGER DEFAULT 0,
    location VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_user ON search_history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_created ON search_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_session ON search_history(session_id);
CREATE INDEX IF NOT EXISTS idx_history_deleted ON search_history(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_SEARCH_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS search_results (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID UNIQUE NOT NULL,
    restaurants JSONB NOT NULL DEFAULT '[]',
    summary TEXT,
    filtered_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_results_session ON search_results(session_id);
"""

CREATE_RESTAURANTS_TABLE = """
CREATE TABLE IF NOT EXISTS restaurants (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    alias VARCHAR(255),
    tel VARCHAR(50),
    address TEXT,
    city VARCHAR(100),
    district VARCHAR(100),
    business_area VARCHAR(100),
    location VARCHAR(50),
    rating REAL,
    cost VARCHAR(50),
    open_time VARCHAR(255),
    trust_score REAL,
    one_liner TEXT,
    tags JSONB DEFAULT '[]',
    pros JSONB DEFAULT '[]',
    cons JSONB DEFAULT '[]',
    warning TEXT,
    must_try JSONB DEFAULT '[]',
    black_list JSONB DEFAULT '[]',
    stats JSONB DEFAULT '{}',
    photos JSONB DEFAULT '[]',
    source_notes JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name);
CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city);
"""
