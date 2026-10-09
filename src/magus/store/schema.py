"""SQLite 인덱스 스키마. 인덱스는 언제든 원본 파일에서 다시 만들 수 있으므로,
스키마가 바뀌면 SCHEMA_VERSION을 올린다. 그러면 LocalStore가 인덱스를 지우고 다시 만든다."""

SCHEMA_VERSION = 21  # 17: 층(#93). 18: refs.moved(공용으로 옮긴 기록). 19: 문서 책(documents, 레인 document)·원고 책 색(#94)
# 20: 컨텍스트(#96). 생각·문체 표(ideas·style_entries)를 빼고 글(category_items)에 칸을 더함, refs.book, contexts 열
# 21: 스크랩(별표, 2026-10-09). category_items.scrap·refs.scrap

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
    "ideas",  # #96 전 표. 지울 때만 이름을 쓴다(옛 인덱스를 지우려고)
    "style_entries",
    "categories",
    "category_items",
    "documents",
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
    subtitle    TEXT,
    title_en    TEXT,
    subtitle_en TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    color       TEXT,
    contexts    TEXT NOT NULL DEFAULT '[]',  -- 올린 문서가 든 책의 컨텍스트(#96)
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
    uncertain_cite_keys    TEXT NOT NULL DEFAULT '[]',  -- 파생값: 장의 미연결 한글 표기 key(outline '미연결')
    version                INTEGER NOT NULL,
    last_note              TEXT NOT NULL DEFAULT '',
    updated_at             TEXT NOT NULL,
    edition                INTEGER,  -- 본문이 같은 업로드 판. NULL이면 Magus에서 고친 본문(또는 판 기록 전)
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
    author          TEXT,
    author_kind     TEXT CHECK (author_kind IN ('ai', 'person')),
    comment_date    TEXT,
    anchor          TEXT,
    paragraph       INTEGER,
    comment_fp      TEXT,
    stale           TEXT CHECK (stale IN ('comment_removed', 'anchor_missing')),
    stale_edition   INTEGER,
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
    updated_at    TEXT,
    floor         TEXT NOT NULL DEFAULT 'common',
    moved         TEXT,
    book          TEXT,  -- 그 글이 꽂힌 책(카테고리 id, #96)
    scrap         INTEGER NOT NULL DEFAULT 0,  -- 스크랩(별표, 2026-10-09). 원본은 bib.json의 "scrap": true
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

-- 책(#92 카테고리 → #96 모든 책). 원본은 shelf/categories/<id>/category.json. schema_version은 파일 형식 버전이다.
CREATE TABLE categories (
    id              TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    name_key        TEXT NOT NULL,
    template        TEXT NOT NULL,
    color           TEXT NOT NULL,
    fields          TEXT NOT NULL DEFAULT '[]',
    schema_version  INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    floor           TEXT NOT NULL DEFAULT 'common',
    contexts        TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (user_id, id),
    UNIQUE (user_id, floor, name_key)
);

CREATE TABLE category_items (
    id              TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    category_id     TEXT NOT NULL,
    title           TEXT,
    title_by        TEXT CHECK (title_by IN ('ai', 'author')),
    content         TEXT NOT NULL,
    fields          TEXT NOT NULL DEFAULT '{}',
    author          TEXT NOT NULL CHECK (author IN ('me', 'ai')),
    tags            TEXT NOT NULL DEFAULT '[]',
    chapters        TEXT NOT NULL DEFAULT '[]',
    schema_version  INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    edited_at       TEXT,
    edited_by       TEXT CHECK (edited_by IN ('author', 'ai')),
    reason          TEXT,
    location        TEXT,
    passages        TEXT NOT NULL DEFAULT '[]',
    parent_id       TEXT,
    origin          TEXT,
    kind            TEXT,
    tags_by         TEXT CHECK (tags_by IN ('ai', 'author')),
    scrap           INTEGER NOT NULL DEFAULT 0,  -- 스크랩(별표, 2026-10-09). 원본은 글 파일의 "scrap": true
    PRIMARY KEY (user_id, category_id, id)
);
CREATE INDEX category_items_scrap ON category_items (user_id, category_id) WHERE scrap = 1;

CREATE TABLE documents (
    id          TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    floor       TEXT NOT NULL,
    title       TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    color       TEXT NOT NULL,
    edition     INTEGER,
    versions    INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    contexts    TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (user_id, id)
);

CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,
    user_id     TEXT NOT NULL,
    owner_type  TEXT NOT NULL,
    owner_id    TEXT NOT NULL,
    lane        TEXT NOT NULL CHECK (lane IN ('ref_picked', 'ref_full', 'idea_me', 'idea_ai', 'style', 'style_passage', 'ref_bib',
                                              'category', 'document')),
    text        TEXT NOT NULL,
    embedding   BLOB
);
CREATE INDEX chunks_owner ON chunks (user_id, owner_type, owner_id);

-- rowid = chunks.id. 한국어 토큰화 방식은 4단계에서 정한다(CLAUDE.md 참고).
CREATE VIRTUAL TABLE chunks_fts USING fts5 (tokens);
"""
