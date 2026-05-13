"""Utilitários para SQL Server — listagem de bases e execução de backup/restore remoto."""
import pymssql


def list_databases(host: str, port: str, user: str, password: str) -> list[tuple[str, str]]:
    """Retorna lista de (nome_base, tamanho_formatado) excluindo system databases."""
    conn = pymssql.connect(
        server=host, port=port, user=user, password=password, database="master"
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    d.name,
                    CAST(ROUND(SUM(mf.size) * 8.0 / 1024, 2) AS DECIMAL(10,2)) AS size_mb
                FROM sys.databases d
                JOIN sys.master_files mf ON d.database_id = mf.database_id
                WHERE d.database_id > 4
                  AND d.state_desc = 'ONLINE'
                GROUP BY d.name
                ORDER BY size_mb DESC
            """)
            rows = cur.fetchall()
            return [(name, f"{size_mb} MB") for name, size_mb in rows]
    finally:
        conn.close()


def run_backup_remote(host: str, port: str, user: str, password: str,
                      database: str, remote_path: str, log_fn=None) -> str:
    """Executa BACKUP DATABASE no servidor remoto. Retorna o caminho do .bak gerado."""
    # Detecta se o path é Linux (/) ou Windows (\)
    if "/" in remote_path and not "\\" in remote_path:
        sep = "/"
    else:
        sep = "\\"

    if not remote_path.endswith(".bak"):
        remote_path = f"{remote_path}{sep}{database}.bak"

    conn = pymssql.connect(
        server=host, port=port, user=user, password=password, database="master"
    )
    try:
        conn.autocommit(True)
        with conn.cursor() as cur:
            # Detecta edição do SQL Server para saber se suporta COMPRESSION
            cur.execute("SELECT SERVERPROPERTY('Edition')")
            edition = str(cur.fetchone()[0]).lower()
            supports_compression = "express" not in edition

            options = "INIT"
            if supports_compression:
                options = "COMPRESSION, INIT"

            sql = f"BACKUP DATABASE [{database}] TO DISK = N'{remote_path}' WITH {options}"
            if log_fn:
                if not supports_compression:
                    log_fn("Aviso: SQL Server Express detectado — backup sem compressão.\n")
                log_fn(f"Executando: {sql}\n")
            cur.execute(sql)
            # Consome mensagens do SQL Server (progresso)
            while cur.nextset():
                pass
        if log_fn:
            log_fn(f"Backup de [{database}] concluído no servidor remoto: {remote_path}\n")
        return remote_path
    finally:
        conn.close()


def run_restore_remote(host: str, port: str, user: str, password: str,
                       database: str, remote_bak_path: str, log_fn=None) -> bool:
    """Executa RESTORE DATABASE no servidor remoto."""
    conn = pymssql.connect(
        server=host, port=port, user=user, password=password, database="master"
    )
    try:
        conn.autocommit(True)
        with conn.cursor() as cur:
            # Coloca em single user para forçar restore
            try:
                cur.execute(f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            except Exception:
                pass  # base pode não existir ainda

            sql = f"RESTORE DATABASE [{database}] FROM DISK = N'{remote_bak_path}' WITH REPLACE"
            if log_fn:
                log_fn(f"Executando: {sql}\n")
            cur.execute(sql)
            while cur.nextset():
                pass

            # Volta para multi user
            try:
                cur.execute(f"ALTER DATABASE [{database}] SET MULTI_USER")
            except Exception:
                pass

        if log_fn:
            log_fn(f"Restore de [{database}] concluído com sucesso.\n")
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"Erro no restore: {str(e)}\n")
        return False
    finally:
        conn.close()
