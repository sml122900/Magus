"""SQLite 인덱스 스키마. 인덱스는 언제든 원본 파일에서 다시 만들 수 있으므로,
스키마가 바뀌면 SCHEMA_VERSION을 올린다. 그러면 LocalStore가 인덱스를 지우고 다시 만든다."""

SCHEMA_VERSION = 7

# 지울 때는 역순으로 지운다. chunks_fts는 가상 테이블이다(그림자 테이블도 함께 지워진다).
TABLES = (
    "users",
    "projects",
    "parts",
    "chapters",
    "chapter_versions",
    "decisions",
    "issues",
    "refs",
    "ref_passages",
    "ideas",
    "style_entries",
    "chunks",
    "chunks_fts",
)

SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY
);

CREATE TABLE projects (
    id          TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE parts (
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    number      INTEGER NOT NULL,
    title       TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id, number)
);

CREATE TABLE chapters (
    id                     INTEGER PRIMARY KEY,
    user_id                TEXT NOT NULL,
    project_id             TEXT NOT NULL,
    number                 INTEGER NOT NULL,
    label                  TEXT,
    title                  TEXT NOT NULL,
    status                 TEXT NOT NULL,
    part_number            INTEGER,
    path                   TEXT NOT NULL,
    char_count             INTEGER NOT NULL,
    unverified_cite_count  INTEGER NOT NULL DEFAULT 0,
    unverified_cite_keys   TEXT NOT NULL DEFAULT '[]',  -- 파생값: 장의 미확인 문헌 key(책 전체 고유 수를 내려고)
    version                INTEGER NOT NULL,
    last_note              TEXT NOT NULL DEFAULT '',
    updated_at             TEXT NOT NULL,
    UNIQUE (user_id, project_id, number)
);

CREATE TABLE chapter_versions (
    id          INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL,
    chapter_id  INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    path        TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (chapter_id, version)
);

CREATE TABLE decisions (
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    id          INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id, id)
);

CREATE TABLE issues (
    user_id         TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    id              INTEGER NOT NULL,
    text            TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    origin          TEXT NOT NULL CHECK (origin IN ('import_comment', 'user', 'agent')),
    chapter_number  INTEGER,
    created_at      TEXT NOT NULL,
    closed_note     TEXT,
    kind            TEXT NOT NULL DEFAULT 'general' CHECK (kind IN ('citation', 'fact', 'general')),
    ref_key         TEXT,
    ref_id          TEXT,
    PRIMARY KEY (user_id, project_id, id)
);

CREATE TABLE refs (
    id            INTEGER PRIMARY KEY,
    user_id       TEXT NOT NULL,
    key           TEXT NOT NULL,
    aliases       TEXT NOT NULL DEFAULT '[]',
    bib           TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL CHECK (status IN ('unverified', 'verified')),
    has_fulltext  INTEGER NOT NULL DEFAULT 0,
    file_path     TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (user_id, key)
);

CREATE TABLE ref_passages (
    id       INTEGER PRIMARY KEY,
    user_id  TEXT NOT NULL,
    ref_id   INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    text     TEXT NOT NULL,
    reason   TEXT NOT NULL,
    locator  TEXT
);

CREATE TABLE ideas (
    id          TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    text        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('thought', 'ai', 'article', 'conversation', 'tv', 'other')),
    origin      TEXT,
    author      TEXT NOT NULL CHECK (author IN ('me', 'ai')),
    parent_id   TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE style_entries (
    id          TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    passage     TEXT NOT NULL,
    reason      TEXT NOT NULL,
    work        TEXT,
    tags        TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, id)
);

CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL,
    owner_type  TEXT NOT NULL,
    owner_id    TEXT NOT NULL,
    lane        TEXT NOT NULL CHECK (lane IN ('ref_picked', 'ref_full', 'idea_me', 'idea_ai', 'style')),
    text        TEXT NOT NULL,
    embedding   BLOB
);
CREATE INDEX chunks_owner ON chunks (user_id, owner_type, owner_id);

-- rowid = chunks.id. 한국어 토큰화 방식은 4단계에서 정한다(CLAUDE.md 참고).
CREATE VIRTUAL TABLE chunks_fts USING fts5 (tokens);
"""
