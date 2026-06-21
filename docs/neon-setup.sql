-- Run this in Neon SQL Editor once
CREATE TABLE IF NOT EXISTS visitor_logs (
  id        bigserial PRIMARY KEY,
  ip        text,
  country   text,
  city      text,
  page      text,
  is_repeat boolean DEFAULT false,
  visited_at timestamptz DEFAULT now()
);
