# Documentação Técnica — Backup2Drive
**Versão:** 2.0.0.0
**Data:** 05/2026

---

## 1. Visão Geral

O **Backup2Drive** é uma aplicação desktop desenvolvida em Python para automatizar o processo de backup e restore de bancos de dados **PostgreSQL** e **SQL Server**, tanto para fluxos de cancelamento contratual quanto para backups pontuais sob demanda.

A ferramenta realiza o backup (local ou remoto), transfere os arquivos entre servidores quando necessário (via SFTP ou SMB), faz o upload automático para o Google Drive e envia uma notificação por e-mail ao cliente via API de e-mail transacional, garantindo rastreabilidade e conformidade.

---

## 2. Arquitetura

### 2.1 Tecnologias Utilizadas

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.13 |
| Interface gráfica | CustomTkinter |
| Empacotamento | PyInstaller |
| Banco de dados local | SQLite 3 |
| Backup PostgreSQL | pg_dump / pg_dumpall / pg_restore (binários embutidos) |
| Backup SQL Server | T-SQL via pymssql (BACKUP DATABASE / RESTORE DATABASE) |
| Transferência de arquivos | paramiko (SFTP) / shutil (SMB/UNC) |
| Armazenamento em nuvem | Google Drive API v3 |
| Notificação | API de e-mail transacional (HMAC-SHA256) |
| Autenticação Google | OAuth 2.0 (InstalledAppFlow) |

### 2.2 Estrutura de Módulos

```
Backup2Drive.exe
├── main.py                          # Interface gráfica (CustomTkinter)
├── core/
│   ├── backup.py                    # Backup PostgreSQL + upload Drive
│   ├── backup_mssql.py             # Backup SQL Server + transferência + upload Drive
│   ├── restore.py                   # Restore PostgreSQL + upgrade remoto via paramiko
│   ├── restore_mssql.py            # Restore SQL Server (transferência reversa)
│   ├── db.py                        # Histórico local (SQLite)
│   ├── process.py                   # Controle de processos e log em tempo real
│   ├── pg_utils.py                  # Listagem de bases PostgreSQL
│   ├── mssql_utils.py              # Listagem de bases e backup/restore SQL Server
│   ├── transfer.py                  # Transferência SFTP/SMB + chmod + browsing remoto
│   ├── config.py                    # Configurações ofuscadas (XOR+base64)
│   └── services/
│       ├── google_drive_service.py  # Integração Google Drive API
│       └── mitte_service.py         # Integração API de e-mail transacional
└── pgbin/                           # Binários PostgreSQL embutidos
    ├── pg_dump.exe
    ├── pg_dumpall.exe
    ├── pg_restore.exe
    ├── psql.exe
    └── *.dll
```

---

## 3. Funcionalidades

### 3.1 Backup — PostgreSQL

- Modos: **dump** (bases individuais) e **dumpall** (cluster completo)
- Seleção de múltiplas bases via checkboxes ou digitação manual
- Listagem de bases disponíveis com tamanhos
- Nomeação automática: `{código_cliente}_{linha_produto}_{base}_{timestamp}.backup`
- Compactação automática em `.zip` para múltiplas bases
- Upload automático para o Google Drive (estrutura de pastas em dois níveis)
- Compartilhamento com e-mail do cliente
- Envio de e-mail via API transacional (template de cancelamento ou pontual)
- Geração de comprovante de envio para auditoria
- Log completo em arquivo

### 3.2 Backup — SQL Server

- Execução remota de `BACKUP DATABASE ... TO DISK` via T-SQL (pymssql)
- Transferência do `.bak` do servidor de banco para o servidor de aplicação:
  - **SFTP (Linux)**: com `chmod 777` automático antes da transferência
  - **SMB (Windows)**: via caminho UNC montado automaticamente (`\\host\c$\...`)
  - **Sem transferência**: arquivo permanece no servidor de banco
- Explorador remoto de diretórios (estilo WinSCP) para SFTP e SMB
- Mesma nomenclatura do PostgreSQL: `{código_cliente}_{linha_produto}_{base}_{timestamp}.bak`
- Upload, e-mail e comprovante seguem o mesmo fluxo do PostgreSQL

### 3.3 Restore — PostgreSQL

- Modos: **normal** (pg_restore / psql) e **upgrade** (pg_upgradecluster via SSH)
- Listagem de bases para seleção do banco de destino
- Log em tempo real

#### 3.3.1 Modo Upgrade (pg_upgradecluster via SSH)

Fluxo completo de upgrade remoto do PostgreSQL via paramiko (sem dependência de plink/PuTTY):

1. **Validação de inputs** — verifica campos SSH e formato das versões (apenas dígitos e pontos)
2. **Conexão SSH** — paramiko com AutoAddPolicy (mesmo padrão do transfer.py)
3. **Configuração do repositório PGDG** — verifica se `/etc/apt/sources.list.d/pgdg.list` existe; se não, importa a chave GPG e adiciona o repositório `apt.postgresql.org` automaticamente
4. **Instalação da nova versão** — `apt-get update` + `apt-get install -y postgresql-{versão}` (opcional, controlado por checkbox)
5. **Execução do pg_upgradecluster** — `pg_upgradecluster -v {nova} {antiga} main` com streaming de output
6. **Registro no histórico** — SUCCESS ou FAIL

Todas as operações usam o padrão `sudo -S` com senha via stdin. A conexão SSH é sempre fechada em `try/finally`.

Campos na UI (modo upgrade):
| Campo | Descrição |
|---|---|
| Host | Endereço do servidor Linux |
| SSH User | Usuário SSH |
| SSH Password | Senha SSH (também usada para sudo) |
| Versão antiga | Versão atual do PostgreSQL (ex: 9.6, 14) |
| Nova versão | Versão alvo (ex: 16) |
| Instalar PostgreSQL no servidor | Checkbox — instala a nova versão antes do upgrade |

### 3.4 Restore — SQL Server

- Fluxo reverso: seleciona `.bak` local → transfere para o servidor de banco → executa `RESTORE DATABASE`
- Transferência:
  - **SFTP (Linux)**: upload + `chmod 777` + restore via T-SQL
  - **SMB (Windows)**: cópia via UNC + restore via T-SQL
  - **Sem transferência**: assume que o path é acessível pelo SQL Server
- Explorador remoto para selecionar diretório destino
- Listagem de bases para seleção do banco de destino
- Validações completas antes da execução

### 3.5 Dashboard

- Histórico de todas as execuções com status (SUCCESS / FAIL / PARTIAL_SUCCESS)
- Filtro por texto e por status
- Paginação com 15 registros por página
- Cards com totalizadores: total, sucesso, falha e última execução

### 3.6 Templates de E-mail

| Template | Finalidade |
|---|---|
| Cancelamento | Notificação formal de cancelamento com link do backup |
| Backup Pontual | Notificação de backup sob demanda com link do backup |

- Seleção obrigatória quando e-mail do cliente é informado
- Feedback visual: botão ativo muda de cor (azul para pontual, vermelho para cancelamento)

---

## 4. Segurança

### 4.1 Credenciais e Segredos

| Item | Tratamento |
|---|---|
| Credenciais da API de e-mail | Ofuscadas com XOR+base64 em `config.py` (não visíveis com `strings`) |
| ID da pasta raiz do Drive | Ofuscado com XOR+base64 em `config.py` |
| `client_secret.json` (OAuth) | Embutido no executável via PyInstaller |
| Token OAuth do Google | Mantido exclusivamente em memória, nunca gravado em disco |
| Senha do PostgreSQL | Variável de ambiente `PGPASSWORD`, removida no `finally` |
| Senha SQL Server | Trafega via pymssql (conexão TCP), não persistida |
| Senha SSH | Em memória durante execução, não persistida |

### 4.2 Autenticação Google Drive

- Protocolo: OAuth 2.0 com fluxo `InstalledAppFlow`
- Escopo: `https://www.googleapis.com/auth/drive`
- Navegador: Chrome ou Edge (com fallback automático)
- Token válido durante a sessão, descartado ao fechar
- Sem armazenamento de refresh token em disco

### 4.3 Comunicação de Rede

| Destino | Protocolo | Porta | Finalidade |
|---|---|---|---|
| Google Drive API | HTTPS | 443 | Upload e gerenciamento de pastas |
| Google OAuth | HTTPS | 443 | Autenticação do técnico |
| API de e-mail | HTTPS | 443 | Envio de e-mail ao cliente |
| Servidor PostgreSQL | TCP | 5432 | Backup/restore e listagem de bases |
| Servidor SQL Server | TCP | 1433 | Backup/restore e listagem de bases |
| Servidor SSH (Linux) | TCP | 22 | Transferência SFTP + chmod + upgrade |
| Servidor SMB (Windows) | TCP | 445 | Transferência via UNC |

### 4.4 Controle de Acesso ao Drive

- Compartilhamento com permissão `writer`
- Tratamento de `invalidSharingRequest` e `shareInNotPermitted`

### 4.5 Proteção contra Injeção

- Comandos externos via lista de argumentos (nunca string shell)
- Inputs SSH/upgrade validados com regex antes da execução (versões aceitam apenas dígitos e pontos)
- Campos SSH validados como strings não-vazias antes de qualquer conexão
- Queries SQL Server parametrizadas via pymssql

### 4.6 Thread Safety

- Estado compartilhado protegido por `threading.Lock()`
- Log e controle de processo com acesso sincronizado

---

## 5. Dados Tratados

| Dado | Origem | Destino | Persistência |
|---|---|---|---|
| Arquivos de backup (.backup, .sql, .bak, .zip) | Servidor do cliente | Local + Google Drive | Permanente no Drive |
| Credenciais do banco | Digitação manual | Memória | Não persistido |
| E-mail do cliente | Digitação manual | API de e-mail | Não persistido |
| Histórico de execuções | Aplicação | SQLite local | Permanente local |
| Logs de execução | Aplicação | Diretório local | Permanente local |
| Comprovante de envio | Aplicação | Diretório local | Permanente local |
| Token OAuth | Google OAuth | Memória | Não persistido |

---

## 6. Dependências Externas

### 6.1 APIs e Serviços

| Serviço | Finalidade | Autenticação |
|---|---|---|
| Google Drive API v3 | Upload e organização de backups | OAuth 2.0 |
| API de e-mail transacional | Envio de e-mail ao cliente | HMAC-SHA256 |

### 6.2 Bibliotecas Python Principais

| Biblioteca | Finalidade |
|---|---|
| customtkinter | Interface gráfica |
| google-auth-oauthlib | Autenticação OAuth Google |
| google-api-python-client | Google Drive API |
| psycopg2-binary | Conexão PostgreSQL |
| pymssql | Conexão SQL Server |
| paramiko | Transferência SFTP, execução SSH remota e upgrade PG |
| requests | Requisições HTTP |
| hypothesis | Property-based testing |
| pytest | Framework de testes |
| pyinstaller | Empacotamento do executável |

---

## 7. Fluxos de Operação

### 7.1 Backup PostgreSQL

```
Seleciona engine "PostgreSQL"
        ↓
Preenche credenciais → Lista bases
        ↓
Seleciona bases + linha de produto + template de e-mail
        ↓
pg_dump para cada base selecionada
        ↓
[Múltiplas bases] → Compactação em .zip
        ↓
Upload para Google Drive (pasta cliente/atendimento)
        ↓
Compartilhamento + E-mail + Comprovante
        ↓
Registro no histórico (SQLite)
```

### 7.2 Backup SQL Server

```
Seleciona engine "SQL Server"
        ↓
Preenche credenciais → Lista bases
        ↓
Seleciona bases + modo de transferência (SFTP/SMB/Sem)
        ↓
BACKUP DATABASE ... TO DISK (executado no servidor remoto via T-SQL)
        ↓
[SFTP] chmod 777 → download via SFTP
[SMB]  cópia via \\host\c$\...
[Sem]  arquivo permanece no servidor
        ↓
[Múltiplas bases] → Compactação em .zip
        ↓
Upload para Google Drive + E-mail + Comprovante
        ↓
Registro no histórico
```

### 7.3 Restore SQL Server

```
Seleciona engine "SQL Server"
        ↓
Preenche credenciais → Lista bases (para escolher destino)
        ↓
Seleciona arquivo .bak local + diretório destino no servidor
        ↓
[SFTP] upload via SFTP → chmod 777
[SMB]  cópia via \\host\c$\...
[Sem]  usa path local como path do servidor
        ↓
RESTORE DATABASE ... FROM DISK (via T-SQL)
        ↓
Registro no histórico
```

### 7.4 Upgrade PostgreSQL (via SSH)

```
Seleciona tipo "upgrade" no Restore PostgreSQL
        ↓
Preenche: Host + SSH User + SSH Password + Versão antiga + Nova versão
        ↓
Validação de inputs (campos obrigatórios + formato de versão)
        ↓
Conexão SSH via paramiko (AutoAddPolicy)
        ↓
[Se "Instalar PostgreSQL" marcado]
    Verifica repositório PGDG → Configura se necessário
        ↓
    apt-get update → apt-get install postgresql-{nova_versão}
        ↓
pg_upgradecluster -v {nova_versão} {versão_antiga} main
        ↓
Streaming de output em tempo real
        ↓
Registro no histórico (SUCCESS / FAIL)
        ↓
Fechamento da conexão SSH (try/finally)
```

---

## 8. Testes

### 8.1 Infraestrutura

| Item | Tecnologia |
|---|---|
| Framework | pytest |
| Property-based testing | Hypothesis |
| Mocking | unittest.mock |
| Cobertura | 127 testes (unit + PBT) |

### 8.2 Arquivos de Teste

| Arquivo | Cobertura |
|---|---|
| `test_config.py` | Ofuscação XOR, decrypt de segredos, variáveis de ambiente |
| `test_validate_upgrade_inputs.py` | Validação de campos SSH e versões |
| `test_run_remote_command.py` | Padrão sudo -S, streaming de output, exit codes |
| `test_install_pg_remote.py` | Fluxo apt-get update/install, falhas, versionamento |
| `test_ensure_pgdg_repo.py` | Configuração do repositório PGDG (idempotência, falhas) |
| `test_helper_functions.py` | open_ssh_connection, ordenação de comandos, cleanup |
| `test_run_restore_upgrade.py` | Fluxo completo do upgrade em run_restore() |
| `test_property_validation.py` | PBT: rejeição de inputs inválidos (200 exemplos/teste) |
| `test_property_commands.py` | PBT: construção correta de comandos (200 exemplos/teste) |
| `test_property_failure.py` | PBT: sinalização de falha para exit codes não-zero |
| `test_property_streaming.py` | PBT: entrega ordenada de todas as linhas de output |
| `test_property_logging.py` | PBT: mensagens de log contêm informações contextuais |

### 8.3 Execução

```bash
# Instalar dependências de teste
pip install hypothesis

# Rodar todos os testes
python -m pytest tests/ -v

# Rodar apenas property-based tests
python -m pytest tests/test_property_*.py -v
```

---

## 9. Requisitos de Ambiente

### 9.1 Servidor de Aplicação (onde o Backup2Drive roda)

- Windows 64-bit
- Acesso de rede ao servidor de banco (PostgreSQL porta 5432 / SQL Server porta 1433)
- Acesso SSH (porta 22) ao servidor Linux quando aplicável
- Acesso SMB (porta 445) ao servidor Windows quando aplicável
- Acesso à internet (porta 443) para Google Drive e API de e-mail
- Google Chrome ou Microsoft Edge (para autenticação OAuth)
- PostgreSQL **não precisa estar instalado** — binários embutidos no exe

### 9.2 Servidor de Banco de Dados

- **PostgreSQL**: usuário com permissão de leitura
- **SQL Server**: usuário com permissão de BACKUP/RESTORE DATABASE
- **Linux (SFTP)**: usuário com acesso SSH e permissão sudo para chmod
- **Windows (SMB)**: acesso administrativo ao share `c$` do servidor

---

## 10. Arquivos Gerados

| Arquivo | Local | Descrição |
|---|---|---|
| `{cliente}_{linha}_{base}_{timestamp}.backup` | Diretório de backup | Backup PostgreSQL individual |
| `{cliente}_{linha}_{base}_{timestamp}.bak` | Diretório de backup | Backup SQL Server individual |
| `{cliente}_{linha}_{timestamp}.zip` | Diretório de backup | Múltiplas bases compactadas |
| `logs/backup_{timestamp}.log` | Subpasta `logs/` | Log do backup PostgreSQL |
| `logs/backup_mssql_{timestamp}.log` | Subpasta `logs/` | Log do backup SQL Server |
| `logs/comprovante_envio_{timestamp}.txt` | Subpasta `logs/` | Comprovante do e-mail enviado |
| `logs_restore/restore_{timestamp}.log` | Subpasta `logs_restore/` | Log do restore PostgreSQL |
| `logs_restore/restore_mssql_{timestamp}.log` | Subpasta `logs_restore/` | Log do restore SQL Server |
| `history.db` | Diretório da aplicação | Histórico de execuções |

---

## 11. Repositório

- **Branch principal:** master
