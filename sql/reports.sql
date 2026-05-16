-- Usage report for indexes managed by this tool.
SELECT
    current_database() AS database_name,
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    idx.relname AS index_name,
    pg_size_pretty(pg_total_relation_size(tbl.oid)) AS table_size,
    pg_size_pretty(pg_relation_size(idx.oid)) AS index_size,
    COALESCE(s.idx_scan, 0) AS idx_scan,
    COALESCE(s.idx_tup_read, 0) AS idx_tup_read,
    COALESCE(s.idx_tup_fetch, 0) AS idx_tup_fetch,
    now() AS checked_at
FROM pg_index i
JOIN pg_class idx ON idx.oid = i.indexrelid
JOIN pg_class tbl ON tbl.oid = i.indrelid
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = idx.oid
WHERE ns.nspname = 'public'
  AND idx.relname LIKE 'idx\_%\_number\_as\_mvarchar%' ESCAPE '\'
ORDER BY tbl.relname, idx.relname;
