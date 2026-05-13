# Backup2Drive

Aplicação desktop para backup, restore e upgrade de bancos PostgreSQL e SQL Server, com upload automático para o Google Drive e notificação por e-mail via Mitte Pro.

## Funcionalidades

- **Backup PostgreSQL** — dump/dumpall com upload pro Drive e e-mail automático
- **Backup SQL Server** — BACKUP DATABASE com transferência SFTP/SMB + upload pro Drive
- **Restore PostgreSQL** — pg_restore/psql com seleção de arquivo
- **Restore SQL Server** — transferência reversa + RESTORE DATABASE
- **Upgrade PostgreSQL** — instalação remota da nova versão + pg_upgradecluster via SSH (paramiko)
- **Dashboard** — histórico de execuções com filtros e paginação

## Requisitos

- Python 3.10+
- PostgreSQL (binários pg_dump/pg_restore embutidos no exe — não precisa instalar)
- Conta Google com OAuth2 configurada

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração

1. Copie `.env.example` para `.env` e preencha com suas credenciais:
   ```
   MITTE_AUTH_KEY=...
   MITTE_SECRET=...
   ROOT_FOLDER=...
   ```

2. Coloque o arquivo `client_secret.json` da sua aplicação Google em `auth/client_secret.json`

## Uso

```bash
python main.py
```

## Build (.exe)

```bash
pyinstaller main.spec
```

O executável é gerado em `dist/Backup2Drive.exe`.

## Testes

```bash
pip install hypothesis
python -m pytest tests/ -v
```

A suite inclui testes unitários e property-based tests (Hypothesis) cobrindo validação de inputs, execução remota SSH, instalação de pacotes e streaming de output.

## Estrutura do Projeto

```
├── main.py                    # Interface gráfica (CustomTkinter)
├── core/
│   ├── backup.py              # Backup PostgreSQL + upload Drive
│   ├── backup_mssql.py        # Backup SQL Server + transferência + upload
│   ├── restore.py             # Restore PostgreSQL + upgrade remoto (paramiko)
│   ├── restore_mssql.py       # Restore SQL Server
│   ├── db.py                  # Histórico local (SQLite)
│   ├── process.py             # Controle de processos e log em tempo real
│   ├── pg_utils.py            # Listagem de bases PostgreSQL
│   ├── mssql_utils.py         # Listagem de bases SQL Server
│   ├── transfer.py            # Transferência SFTP/SMB + browsing remoto
│   ├── config.py              # Configurações ofuscadas (XOR+base64)
│   └── services/
│       ├── google_drive_service.py
│       └── mitte_service.py
├── pgbin/                     # Binários PostgreSQL embutidos
├── tests/                     # Testes unitários e property-based
├── tools/                     # Scripts auxiliares
└── auth/                      # Credenciais OAuth Google
```
