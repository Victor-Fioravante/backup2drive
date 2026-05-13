import psycopg2


def list_databases(host, port, user, password):
    conn = psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname="postgres"
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT datname, pg_size_pretty(pg_database_size(datname))
                FROM pg_database
                WHERE datistemplate = false
                ORDER BY pg_database_size(datname) DESC
            """)
            return cur.fetchall()
    finally:
        conn.close()
