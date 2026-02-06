-- Coach Database Schema
-- Single source of truth for college football coaching data

-- Conferences
CREATE TABLE IF NOT EXISTS conferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    abbrev TEXT UNIQUE NOT NULL,       -- 'SEC', 'Big 10', etc.
    name TEXT NOT NULL,                -- 'Southeastern Conference'
    division TEXT DEFAULT 'FBS'        -- 'FBS', 'FCS'
);

-- Schools
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                -- 'Alabama'
    slug TEXT UNIQUE,                  -- 'alabama' (for URLs/lookups)
    conference_id INTEGER,
    state TEXT,                        -- 'AL'
    city TEXT,
    cfbstats_code INTEGER,             -- 8 (for cfbstats.com integration)
    FOREIGN KEY (conference_id) REFERENCES conferences(id)
);

-- Coaches
CREATE TABLE IF NOT EXISTS coaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    school_id INTEGER,
    position TEXT,                     -- 'Head Coach', 'Offensive Coordinator', etc.
    is_head_coach BOOLEAN DEFAULT 0,
    year INTEGER DEFAULT 2025,         -- Season year
    
    -- From CollegePressBox/scrape
    cpb_scraped_at TEXT,              -- When scraped from CollegePressBox
    
    FOREIGN KEY (school_id) REFERENCES schools(id)
);

-- Head Coach Salaries (from USA Today, state DBs, media)
CREATE TABLE IF NOT EXISTS salaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    total_pay INTEGER,                 -- Total annual compensation
    school_pay INTEGER,                -- Base school salary
    max_bonus INTEGER,
    bonuses_paid INTEGER,
    buyout INTEGER,
    source TEXT,                       -- 'usa_today', 'texas_tribune', 'media'
    source_date TEXT,                  -- When data was published
    FOREIGN KEY (coach_id) REFERENCES coaches(id)
);

-- Salary data sources per school (assistant + staff salary scraping)
CREATE TABLE IF NOT EXISTS salary_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,         -- 'osu_hr', 'transparent_ca', 'unc_system', etc.
    base_url TEXT NOT NULL,
    query_params TEXT,                 -- JSON string (per-source config)
    parser_name TEXT NOT NULL,         -- Parser dispatch key
    last_scraped TEXT,                 -- ISO timestamp
    active BOOLEAN DEFAULT 1,
    FOREIGN KEY (school_id) REFERENCES schools(id)
);

-- Coaching Trees (who mentored whom)
CREATE TABLE IF NOT EXISTS coaching_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL,
    mentor_id INTEGER NOT NULL,
    relationship TEXT,                 -- 'position_coach', 'coordinator', 'ga'
    start_year INTEGER,
    end_year INTEGER,
    school_id INTEGER,                 -- Where they worked together
    FOREIGN KEY (coach_id) REFERENCES coaches(id),
    FOREIGN KEY (mentor_id) REFERENCES coaches(id),
    FOREIGN KEY (school_id) REFERENCES schools(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_coaches_school ON coaches(school_id);
CREATE INDEX IF NOT EXISTS idx_coaches_position ON coaches(position);
CREATE INDEX IF NOT EXISTS idx_coaches_name ON coaches(name);
CREATE INDEX IF NOT EXISTS idx_salaries_coach ON salaries(coach_id);
CREATE INDEX IF NOT EXISTS idx_salaries_year ON salaries(year);
CREATE INDEX IF NOT EXISTS idx_salary_sources_school ON salary_sources(school_id);
CREATE INDEX IF NOT EXISTS idx_salary_sources_active ON salary_sources(active);
