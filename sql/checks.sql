-- Primary check. The tool refuses run mode when this returns false.
SELECT NOT pg_is_in_recovery() AS is_primary;

-- Required 1C/Postgres Pro data types.
SELECT n.nspname AS schema_name, t.typname AS type_name
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE t.typname IN ('mchar', 'mvarchar')
ORDER BY n.nspname, t.typname;

-- Required operator class for the expression index.
SELECT n.nspname AS schema_name, opc.opcname AS operator_class, am.amname AS access_method
FROM pg_opclass opc
JOIN pg_namespace n ON n.oid = opc.opcnamespace
JOIN pg_am am ON am.oid = opc.opcmethod
WHERE opc.opcname = 'mvarchar_icase_ops'
ORDER BY n.nspname, opc.opcname;

-- Invalid or not-ready 1C number expression indexes.
SELECT
    current_database() AS database_name,
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    idx.relname AS index_name,
    i.indisvalid,
    i.indisready,
    pg_size_pretty(pg_relation_size(idx.oid)) AS index_size,
    pg_get_indexdef(idx.oid) AS index_definition
FROM pg_index i
JOIN pg_class idx ON idx.oid = i.indexrelid
JOIN pg_class tbl ON tbl.oid = i.indrelid
JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
WHERE ns.nspname = 'public'
  AND idx.relname LIKE 'idx\_%\_number\_as\_mvarchar%' ESCAPE '\'
  AND (NOT i.indisvalid OR NOT i.indisready)
ORDER BY tbl.relname, idx.relname;
