import sys
import os
import traceback
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.db import init_db, get_history, delete_history, delete_all_history
from core.backup import run_backup
from core.backup_mssql import run_backup_mssql
from core.restore import run_restore
from core.restore_mssql import run_restore_mssql
from core.process import cancel_process, get_log, is_running
from core.services.google_drive_service import GoogleDriveService
from core.pg_utils import list_databases as pg_list_databases
from core.mssql_utils import list_databases as mssql_list_databases
from core.transfer import browse_sftp, browse_smb

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_BG = "#0f172a"
CARD_BG = "#1e293b"


def create_card(parent, title, value, color):
    frame = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12)

    frame.grid_rowconfigure(1, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(frame, text=title, text_color="#94a3b8", anchor="center").grid(row=0, column=0, pady=(10, 0), sticky="ew")
    value_label = ctk.CTkLabel(frame, text=value, text_color=color, font=("Arial", 22, "bold"), anchor="center")
    value_label.grid(row=1, column=0, pady=(5, 10), sticky="ew")

    frame.value_label = value_label
    return frame


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Backup2Drive")
        self.geometry("1000x750")
        self.minsize(800, 600)
        self.configure(fg_color=APP_BG)

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        icon_path = os.path.join(base_path, "backup.ico")

        try:
            self.iconbitmap(icon_path)
        except Exception as e:
            print(f"Aviso: Não foi possível carregar o ícone da janela. {e}")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, fg_color="#020617")
        sidebar.grid(row=0, column=0, sticky="ns")

        sidebar.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(sidebar, text="Backup2Drive", font=("Arial", 16, "bold")).grid(row=0, column=0, pady=20, padx=10)

        ctk.CTkButton(sidebar, text="📊 Dashboard", command=self.show_dashboard).grid(row=1, column=0, sticky="ew",
                                                                                     padx=10, pady=5)
        ctk.CTkButton(sidebar, text="💾 Backup", command=self.show_backup).grid(row=2, column=0, sticky="ew", padx=10,
                                                                               pady=5)
        ctk.CTkButton(sidebar, text="♻️ Restore", command=self.show_restore).grid(row=3, column=0, sticky="ew", padx=10,
                                                                                  pady=5)

        ctk.CTkButton(sidebar, text="Google Drive Auth", command=self.api_drive).grid(row=15, column=0, sticky="ew",
                                                                                      padx=10, pady=5)

        self.container = ctk.CTkFrame(self, fg_color=APP_BG)
        self.container.grid(row=0, column=1, sticky="nsew")

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.pages = {}
        for Page in (DashboardPage, BackupPage, RestorePage):
            page = Page(self.container, self)
            self.pages[Page.__name__] = page
            page.grid(row=0, column=0, sticky="nsew")

        self.show_dashboard()
        self.update_log_loop()

    def show_dashboard(self):
        self.pages["DashboardPage"].tkraise()
        self.pages["DashboardPage"].load()

    def show_backup(self):
        self.pages["BackupPage"].tkraise()

    def show_restore(self):
        self.pages["RestorePage"].tkraise()

    def update_log_loop(self):
        self.pages["BackupPage"].update_log()
        self.pages["RestorePage"].update_log()
        self.after(1000, self.update_log_loop)

    def api_drive(self):
        def background_auth():
            try:
                service = GoogleDriveService()
                service.authenticate()
                messagebox.showinfo("Sucesso", "Autenticação no Google Drive concluída com sucesso!")
            except Exception:
                messagebox.showerror("Erro Fatal na Autenticação", f"Ocorreu um erro:\n\n{traceback.format_exc()}")

        threading.Thread(target=background_auth, daemon=True).start()


class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=APP_BG)

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))

        for i in range(4):
            cards.grid_columnconfigure(i, weight=2)

        self.card_total = create_card(cards, "Total", "0", "#3b82f6")
        self.card_success = create_card(cards, "Sucesso", "0", "#22c55e")
        self.card_fail = create_card(cards, "Falha", "0", "#ef4444")
        self.card_last = create_card(cards, "Última Execução", "-", "#3b82f6")

        self.card_total.grid(row=0, column=0, sticky="nsew", padx=5)
        self.card_success.grid(row=0, column=1, sticky="nsew", padx=5)
        self.card_fail.grid(row=0, column=2, sticky="nsew", padx=5)
        self.card_last.grid(row=0, column=3, sticky="nsew", padx=5)

        self.search_var = ctk.StringVar()
        self.filter_var = ctk.StringVar(value="Todos")

        filters = ctk.CTkFrame(self)
        filters.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))

        filters.grid_columnconfigure(0, weight=1)

        ctk.CTkEntry(filters, textvariable=self.search_var).grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=8)
        ctk.CTkOptionMenu(filters, values=["Todos", "Sucesso", "Falha"],
                          variable=self.filter_var, command=self.apply_filters).grid(row=0, column=1, padx=(0, 10), pady=8)

        ctk.CTkButton(self, text="️Limpar Histórico",
                      fg_color="#dc2626", command=self.clear_all).grid(row=2, column=0, pady=(0, 8))

        self.table_frame = ctk.CTkScrollableFrame(self)
        self.table_frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 10))

        headers = ["ID", "Data", "Tipo", "Destino", "Status", "Ação"]
        for col, text in enumerate(headers):
            self.table_frame.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(self.table_frame, text=text, font=("Arial", 12, "bold")).grid(row=0, column=col, padx=8, pady=(8, 4))

        nav = ctk.CTkFrame(self)
        nav.grid(row=4, column=0, pady=(0, 10))

        ctk.CTkButton(nav, text="⬅️", command=self.prev_page).pack(side="left")
        ctk.CTkButton(nav, text="➡️", command=self.next_page).pack(side="left")

        self.current_page = 0
        self.page_size = 15
        self.filtered_rows = []
        self._all_rows = []

        self.search_var.trace_add("write", self.apply_filters)

    def load(self):
        self._all_rows = get_history()

        self.card_total.value_label.configure(text=len(self._all_rows))
        self.card_success.value_label.configure(text=sum(1 for r in self._all_rows if r[4] == "SUCCESS"))
        self.card_fail.value_label.configure(text=sum(1 for r in self._all_rows if r[4] == "FAIL"))

        if self._all_rows:
            raw = self._all_rows[0][1]
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(raw)
                data_fmt = dt.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                data_fmt = raw
            self.card_last.value_label.configure(text=data_fmt)

        self.apply_filters()

    def apply_filters(self, *_):
        rows = self._all_rows
        search = self.search_var.get().lower()

        if search:
            rows = [r for r in rows if search in str(r).lower()]

        if self.filter_var.get() == "Sucesso":
            rows = [r for r in rows if r[4] == "SUCCESS"]
        elif self.filter_var.get() == "Falha":
            rows = [r for r in rows if r[4] == "FAIL"]

        self.filtered_rows = rows
        self.current_page = 0
        self.render_page()

    def render_page(self):
        start = self.current_page * self.page_size
        end = start + self.page_size
        self.render_table(self.filtered_rows[start:end])

    def render_table(self, rows):
        for w in self.table_frame.winfo_children():
            if int(w.grid_info()["row"]) > 0:
                w.destroy()

        for i, row in enumerate(rows, start=1):
            history_id, time, type_, target, status = row
            color = "#22c55e" if status == "SUCCESS" else "#ef4444"

            for col, val in enumerate([history_id, time, type_, target]):
                ctk.CTkLabel(self.table_frame, text=str(val)).grid(row=i, column=col, sticky="w", padx=8, pady=3)

            ctk.CTkLabel(self.table_frame, text=status, text_color=color).grid(row=i, column=4, padx=8, pady=3)

            ctk.CTkButton(self.table_frame, text="X", width=30,
                          fg_color="#dc2626",
                          command=lambda hid=history_id: self.delete_item(hid)).grid(row=i, column=5, padx=8, pady=3)

    def delete_item(self, history_id):
        if messagebox.askyesno("Confirmar", "Excluir registro?"):
            delete_history(history_id)
            self.load()

    def clear_all(self):
        if messagebox.askyesno("Confirmar", "Limpar histórico completo?"):
            delete_all_history()
            self.load()

    def next_page(self):
        if (self.current_page + 1) * self.page_size < len(self.filtered_rows):
            self.current_page += 1
            self.render_page()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()


class BackupPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=APP_BG)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ── GRID DE INPUTS (topo) ──
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 5))
        form.grid_columnconfigure((0, 1, 2, 3), weight=1)

        def fe(ph, show=None):
            return ctk.CTkEntry(form, placeholder_text=ph, show=show)

        # Row 0: Engine selector + conexão
        self.engine = ctk.CTkOptionMenu(form, values=["PostgreSQL", "SQL Server"], command=self.toggle_engine)
        self.engine.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.host = fe("Host")
        self.port = fe("Porta")
        self.port.insert(0, "5432")
        self.user = fe("Usuário")
        self.user.insert(0, "PGADMIN")
        self.password = fe("Senha", "*")

        self.host.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.port.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        self.user.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self.password.grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        # Row 1: Tipo backup + database
        self.type = ctk.CTkOptionMenu(form, values=["dump", "dumpall"], command=self.toggle_type)
        self.type.grid(row=1, column=2, sticky="ew", padx=4, pady=4)

        self.database = ctk.CTkEntry(form, placeholder_text="Base(s) separadas por vírgula (ou selecione abaixo)")
        self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)

        # Row 2: Diretório local
        self.dir = ctk.CTkEntry(form, placeholder_text="Diretório Local")
        self.dir.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
        ctk.CTkButton(form, text="Selecionar Pasta", width=130, command=self.select_folder).grid(row=2, column=3, sticky="ew", padx=4, pady=4)

        # Row 3: Drive
        self.drive_folder = fe("Pasta Principal no Drive (Código do Cliente)")
        self.drive_subfolder = fe("Subpasta no Drive (N° Atendimento)")
        self.linha_produto = ctk.CTkOptionMenu(form, values=["SHOP", "PACK", "IMMOBILE", "BIMER"])
        self.client_email = fe("E-mail para Permissão e Envio (Opcional)")

        self.drive_folder.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.drive_subfolder.grid(row=3, column=2, sticky="ew", padx=4, pady=4)
        self.linha_produto.grid(row=3, column=3, sticky="ew", padx=4, pady=4)
        self.client_email.grid(row=4, column=0, columnspan=3, sticky="ew", padx=4, pady=4)

        # Toggle Backup Pontual / Cancelamento
        self._template_type = None  # Nenhum selecionado por padrão
        self.btn_pontual = ctk.CTkButton(form, text="Backup Pontual", fg_color="#475569",
                                         command=lambda: self._set_template("pontual"))
        self.btn_cancelamento = ctk.CTkButton(form, text="Cancelamento", fg_color="#dc2626",
                                              command=lambda: self._set_template("cancelamento"))
        self.btn_pontual.grid(row=4, column=3, sticky="w", padx=(4, 2), pady=4)
        self.btn_cancelamento.grid(row=4, column=3, sticky="e", padx=(2, 4), pady=4)

        # Ajusta layout: email ocupa 3 colunas, botões na coluna 3
        # Reposiciona os botões lado a lado na row 4 col 3
        # Usa um sub-frame para os dois botões
        self.btn_pontual.grid_forget()
        self.btn_cancelamento.grid_forget()

        template_frame = ctk.CTkFrame(form, fg_color="transparent")
        template_frame.grid(row=4, column=3, sticky="ew", padx=4, pady=4)
        template_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_pontual = ctk.CTkButton(template_frame, text="Pontual", fg_color="#475569",
                                         command=lambda: self._set_template("pontual"))
        self.btn_pontual.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.btn_cancelamento = ctk.CTkButton(template_frame, text="Cancelamento", fg_color="#475569",
                                              command=lambda: self._set_template("cancelamento"))
        self.btn_cancelamento.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # Row 5-6: Campos de transferência (SQL Server)
        self.transfer_mode = ctk.CTkOptionMenu(form, values=["Sem Transferência", "SFTP (Linux)", "SMB (Windows)"],
                                               command=self.toggle_transfer)
        self.transfer_mode.grid(row=5, column=0, sticky="ew", padx=4, pady=4)

        self.remote_bak_dir = fe("Diretório .bak no servidor DB")
        self.remote_bak_dir.grid(row=5, column=1, columnspan=2, sticky="ew", padx=4, pady=4)

        self.browse_remote_btn = ctk.CTkButton(form, text="📂 Explorar", width=100, command=self.browse_remote_dir)
        self.browse_remote_btn.grid(row=5, column=3, sticky="ew", padx=4, pady=4)

        # SFTP: só precisa de porta, user e senha (host = mesmo do banco)
        self.transfer_port = fe("Porta SSH")
        self.transfer_port.insert(0, "22")
        self.transfer_user = fe("Usuário SSH")
        self.transfer_password = fe("Senha SSH", "*")

        self.transfer_port.grid(row=6, column=0, sticky="ew", padx=4, pady=4)
        self.transfer_user.grid(row=6, column=1, sticky="ew", padx=4, pady=4)
        self.transfer_password.grid(row=6, column=2, columnspan=2, sticky="ew", padx=4, pady=4)

        # Widgets de transferência (para show/hide)
        self._transfer_widgets = [self.transfer_mode, self.remote_bak_dir, self.browse_remote_btn,
                                  self.transfer_port, self.transfer_user, self.transfer_password]
        self._sftp_widgets = [self.transfer_port, self.transfer_user, self.transfer_password]

        # ── BOTOES ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(btn_frame, text="🔍 Listar Bases", command=self.listar_bases).grid(row=0, column=0, sticky="ew", padx=4)
        ctk.CTkButton(btn_frame, text="Executar Backup", command=self.start_backup).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(btn_frame, text="🗑️ Limpar Campos", fg_color="#475569", command=self.limpar_campos_backup).grid(row=0, column=2, sticky="ew", padx=4)
        self.cancel_btn = ctk.CTkButton(btn_frame, text="Cancelar", fg_color="#ef4444", command=cancel_process)
        self.cancel_btn.grid(row=0, column=3, sticky="ew", padx=4)

        # ── PAINEL INFERIOR: bases | log ──
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 10))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=2)
        bottom.grid_rowconfigure(0, weight=1)

        self.db_list_frame = ctk.CTkScrollableFrame(bottom)
        self.db_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.db_list_frame.grid_columnconfigure(0, weight=1)

        self.log = ctk.CTkTextbox(bottom)
        self.log.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        # Estado inicial: PostgreSQL (esconde campos SQL Server)
        self.toggle_engine("PostgreSQL")

    def _set_template(self, template_type: str):
        """Alterna entre Backup Pontual e Cancelamento com feedback visual."""
        self._template_type = template_type
        if template_type == "pontual":
            self.btn_pontual.configure(fg_color="#3b82f6")
            self.btn_cancelamento.configure(fg_color="#475569")
        else:
            self.btn_pontual.configure(fg_color="#475569")
            self.btn_cancelamento.configure(fg_color="#dc2626")

    def toggle_engine(self, value):
        """Alterna entre PostgreSQL e SQL Server — mostra/esconde campos relevantes."""
        if value == "SQL Server":
            self.port.delete(0, "end")
            self.port.insert(0, "1433")
            self.user.delete(0, "end")
            self.user.insert(0, "sa")
            # Esconde tipo dump/dumpall (irrelevante para SQL Server)
            self.type.grid_remove()
            self.type.set("dump")
            # Database ocupa o espaço do type
            self.database.grid(row=1, column=2, columnspan=2, sticky="ew", padx=4, pady=4)
            # Mostra campos de transferência
            self.transfer_mode.grid(row=5, column=0, sticky="ew", padx=4, pady=4)
            self.remote_bak_dir.grid(row=5, column=1, columnspan=2, sticky="ew", padx=4, pady=4)
            self.browse_remote_btn.grid(row=5, column=3, sticky="ew", padx=4, pady=4)
            self.toggle_transfer(self.transfer_mode.get())
        else:
            self.port.delete(0, "end")
            self.port.insert(0, "5432")
            self.user.delete(0, "end")
            self.user.insert(0, "PGADMIN")
            # Mostra tipo dump/dumpall
            self.type.configure(values=["dump", "dumpall"])
            self.type.set("dump")
            self.type.grid(row=1, column=2, sticky="ew", padx=4, pady=4)
            self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)
            # Esconde todos os campos de transferência
            for w in self._transfer_widgets:
                w.grid_remove()

    def toggle_transfer(self, value):
        """Mostra/esconde campos de SFTP ou SMB e ajusta diretório padrão."""
        # Esconde campos SFTP
        for w in self._sftp_widgets:
            w.grid_remove()

        # Ajusta diretório padrão conforme modo
        self.remote_bak_dir.delete(0, "end")
        if "SFTP" in value:
            self.remote_bak_dir.insert(0, "/mnt/sdb/backup")
            self.transfer_port.grid(row=6, column=0, sticky="ew", padx=4, pady=4)
            self.transfer_user.grid(row=6, column=1, sticky="ew", padx=4, pady=4)
            self.transfer_password.grid(row=6, column=2, columnspan=2, sticky="ew", padx=4, pady=4)
        elif "SMB" in value:
            # SMB usa o host do banco + admin share (\\host\c$\...)
            self.remote_bak_dir.insert(0, "C:\\Program Files\\Microsoft SQL Server\\MSSQL16.MSSQLSERVER\\MSSQL\\Backup")
        else:
            self.remote_bak_dir.insert(0, "C:\\Program Files\\Microsoft SQL Server\\MSSQL16.MSSQLSERVER\\MSSQL\\Backup")

    def browse_remote_dir(self):
        """Abre janela de exploração remota de diretórios (estilo WinSCP)."""
        transfer_sel = self.transfer_mode.get()
        db_host = self.host.get()

        if not db_host:
            messagebox.showwarning("Atenção", "Preencha o Host do banco de dados primeiro.")
            return

        if "SFTP" in transfer_sel:
            user = self.transfer_user.get()
            password = self.transfer_password.get()
            port = int(self.transfer_port.get() or 22)

            if not all([user, password]):
                messagebox.showwarning("Atenção", "Preencha Usuário e Senha SSH para explorar.")
                return

            start_path = self.remote_bak_dir.get() or "/mnt/sdb/backup"
            RemoteBrowserWindow(self, mode="sftp", start_path=start_path,
                                ssh_host=db_host, ssh_user=user, ssh_password=password, ssh_port=port,
                                on_select=self._set_remote_dir)

        elif "SMB" in transfer_sel:
            # Monta UNC automaticamente: \\host\c$\path
            remote_dir = self.remote_bak_dir.get()
            # Converte C:\path para \\host\c$\path
            if len(remote_dir) >= 2 and remote_dir[1] == ":":
                drive_letter = remote_dir[0].lower()
                rest = remote_dir[2:]
                unc_path = f"\\\\{db_host}\\{drive_letter}${rest}"
            else:
                unc_path = f"\\\\{db_host}\\{remote_dir}"

            RemoteBrowserWindow(self, mode="smb", start_path=unc_path,
                                on_select=self._set_remote_dir_from_unc)
        else:
            # Sem transferência — usa filedialog local como fallback
            path = filedialog.askdirectory()
            if path:
                self._set_remote_dir(path)

    def _set_remote_dir(self, path: str):
        """Callback: define o diretório remoto selecionado."""
        self.remote_bak_dir.delete(0, "end")
        self.remote_bak_dir.insert(0, path)

    def _set_remote_dir_from_unc(self, unc_path: str):
        """Callback SMB: converte UNC de volta para caminho local no servidor."""
        # \\host\c$\path -> C:\path
        parts = unc_path.lstrip("\\").split("\\", 2)  # [host, c$, rest...]
        if len(parts) >= 2 and parts[1].endswith("$"):
            drive_letter = parts[1][0].upper()
            rest = parts[2] if len(parts) > 2 else ""
            local_path = f"{drive_letter}:\\{rest}"
        else:
            local_path = unc_path
        self.remote_bak_dir.delete(0, "end")
        self.remote_bak_dir.insert(0, local_path)

    def limpar_campos_backup(self):
        self.host.delete(0, "end")
        self.database.delete(0, "end")
        self.dir.delete(0, "end")
        self.drive_folder.delete(0, "end")
        self.drive_subfolder.delete(0, "end")
        self.client_email.delete(0, "end")
        self.transfer_user.delete(0, "end")
        self.transfer_password.delete(0, "end")
        self._template_type = None
        self.btn_pontual.configure(fg_color="#475569")
        self.btn_cancelamento.configure(fg_color="#475569")
        for w in self.db_list_frame.winfo_children():
            w.destroy()

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.dir.delete(0, "end")
            self.dir.insert(0, path)

    def listar_bases(self):
        for w in self.db_list_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.db_list_frame, text="Conectando...", text_color="#94a3b8").grid(row=0, column=0)

        engine = self.engine.get()

        def _fetch():
            try:
                if engine == "SQL Server":
                    bases = mssql_list_databases(
                        self.host.get(), self.port.get(),
                        self.user.get(), self.password.get()
                    )
                else:
                    bases = pg_list_databases(
                        self.host.get(), self.port.get(),
                        self.user.get(), self.password.get()
                    )
                self.after(0, lambda: self._render_bases(bases))
            except Exception as e:
                self.after(0, lambda: self._render_bases_erro(str(e)))

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_bases(self, bases):
        for w in self.db_list_frame.winfo_children():
            w.destroy()
        self._checkboxes = {}
        for i, (nome, tamanho) in enumerate(bases):
            var = ctk.BooleanVar()
            cb = ctk.CTkCheckBox(
                self.db_list_frame,
                text=f"{nome}  ({tamanho})",
                variable=var,
                command=self._atualizar_campo_database
            )
            cb.grid(row=i, column=0, sticky="w", pady=2, padx=5)
            self._checkboxes[nome] = var

    def _render_bases_erro(self, erro):
        for w in self.db_list_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.db_list_frame, text=f"Erro: {erro}", text_color="#ef4444").grid(row=0, column=0)

    def _atualizar_campo_database(self):
        selecionadas = [nome for nome, var in self._checkboxes.items() if var.get()]
        self.database.delete(0, "end")
        self.database.insert(0, ", ".join(selecionadas))

    def toggle_type(self, value):
        if value == "dumpall":
            self.database.grid_remove()
        else:
            self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)

    def start_backup(self):
        databases_raw = self.database.get()
        databases = [d.strip() for d in databases_raw.split(",") if d.strip()]

        # Validação: se tem e-mail do cliente, precisa selecionar o modelo de e-mail
        client_email = self.client_email.get().strip()
        if client_email and self._template_type is None:
            messagebox.showwarning(
                "Modelo de E-mail",
                "Selecione o modelo de e-mail (Pontual ou Cancelamento) antes de executar o backup."
            )
            return

        engine = self.engine.get()

        data = {
            "host": self.host.get(),
            "port": self.port.get(),
            "user": self.user.get(),
            "password": self.password.get(),
            "databases": databases,
            "database": databases_raw,
            "backupdir": self.dir.get(),
            "type": self.type.get(),
            "drive_folder": self.drive_folder.get(),
            "drive_subfolder": self.drive_subfolder.get(),
            "linha_produto": self.linha_produto.get(),
            "client_email": self.client_email.get(),
            "template_type": self._template_type
        }

        if engine == "SQL Server":
            # Campos extras para SQL Server
            transfer_sel = self.transfer_mode.get()
            if "SFTP" in transfer_sel:
                data["transfer_mode"] = "sftp"
                data["transfer_host"] = self.host.get()  # mesmo host do banco
                data["transfer_port"] = self.transfer_port.get()
                data["transfer_user"] = self.transfer_user.get()
                data["transfer_password"] = self.transfer_password.get()
            elif "SMB" in transfer_sel:
                data["transfer_mode"] = "smb"
                # Monta UNC automaticamente: \\host\c$\path
                remote_dir = self.remote_bak_dir.get()
                db_host = self.host.get()
                if len(remote_dir) >= 2 and remote_dir[1] == ":":
                    drive_letter = remote_dir[0].lower()
                    rest = remote_dir[2:]
                    data["smb_unc_prefix"] = f"\\\\{db_host}\\{drive_letter}${rest}"
                else:
                    data["smb_unc_prefix"] = f"\\\\{db_host}\\{remote_dir}"
            else:
                data["transfer_mode"] = "none"

            data["remote_bak_dir"] = self.remote_bak_dir.get()
            threading.Thread(target=run_backup_mssql, args=(data,), daemon=True).start()
        else:
            threading.Thread(target=run_backup, args=(data,), daemon=True).start()

    def update_log(self):
        log = get_log()
        if len(log) != getattr(self, '_last_log_len', -1):
            self._last_log_len = len(log)
            self.log.delete("0.0", "end")
            self.log.insert("0.0", "".join(log))
        self.cancel_btn.configure(state="normal" if is_running() else "disabled")


class RemoteBrowserWindow(ctk.CTkToplevel):
    """Janela de exploração remota de diretórios (estilo WinSCP)."""

    def __init__(self, parent, mode: str, start_path: str, on_select,
                 ssh_host=None, ssh_user=None, ssh_password=None, ssh_port=22):
        super().__init__(parent)

        self.title("Explorar Diretório Remoto")
        self.geometry("600x450")
        self.configure(fg_color=APP_BG)
        self.transient(parent)
        self.grab_set()

        self.mode = mode
        self.on_select = on_select
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.ssh_port = ssh_port
        self.current_path = start_path

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Barra de caminho
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        nav.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(nav, text="⬆️ Subir", width=80, command=self.go_up).grid(row=0, column=0, padx=(0, 5))
        self.path_entry = ctk.CTkEntry(nav)
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5))
        self.path_entry.insert(0, self.current_path)
        self.path_entry.bind("<Return>", lambda e: self.navigate(self.path_entry.get()))
        ctk.CTkButton(nav, text="Ir", width=50, command=lambda: self.navigate(self.path_entry.get())).grid(row=0, column=2)

        # Lista de arquivos
        self.file_list = ctk.CTkScrollableFrame(self)
        self.file_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.file_list.grid_columnconfigure(0, weight=1)

        # Botões inferiores
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
        bottom.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(bottom, text="✅ Selecionar esta pasta", command=self.confirm_selection).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(bottom, text="Cancelar", fg_color="#475569", command=self.destroy).grid(row=0, column=1)

        # Status
        self.status_label = ctk.CTkLabel(self, text="Carregando...", text_color="#94a3b8")
        self.status_label.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 5))

        # Carrega diretório inicial
        self.navigate(self.current_path)

    def navigate(self, path: str):
        """Navega para o diretório especificado."""
        self.current_path = path
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, path)
        self.status_label.configure(text="Carregando...")

        def _load():
            try:
                if self.mode == "sftp":
                    entries = browse_sftp(self.ssh_host, self.ssh_user, self.ssh_password,
                                          path, self.ssh_port)
                else:
                    entries = browse_smb(path)
                self.after(0, lambda: self._render_entries(entries))
            except Exception as e:
                self.after(0, lambda: self._render_error(str(e)))

        threading.Thread(target=_load, daemon=True).start()

    def _render_entries(self, entries):
        """Renderiza a lista de arquivos/pastas."""
        for w in self.file_list.winfo_children():
            w.destroy()

        if not entries:
            ctk.CTkLabel(self.file_list, text="(vazio)", text_color="#94a3b8").grid(row=0, column=0)
            self.status_label.configure(text=f"{self.current_path}")
            return

        for i, entry in enumerate(entries):
            icon = "📁" if entry.is_dir else "📄"
            size_str = f"  ({entry.size / 1024 / 1024:.1f} MB)" if not entry.is_dir and entry.size > 0 else ""
            text = f"{icon} {entry.name}{size_str}"

            btn = ctk.CTkButton(
                self.file_list,
                text=text,
                anchor="w",
                fg_color="transparent",
                hover_color="#334155",
                command=lambda e=entry: self._on_click(e)
            )
            btn.grid(row=i, column=0, sticky="ew", pady=1)

        dir_count = sum(1 for e in entries if e.is_dir)
        file_count = len(entries) - dir_count
        self.status_label.configure(text=f"{self.current_path}  —  {dir_count} pastas, {file_count} arquivos")

    def _render_error(self, error: str):
        """Mostra erro na lista."""
        for w in self.file_list.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.file_list, text=f"Erro: {error}", text_color="#ef4444").grid(row=0, column=0)
        self.status_label.configure(text="Erro ao carregar")

    def _on_click(self, entry):
        """Ao clicar em um item: navega se for pasta."""
        if entry.is_dir:
            self.navigate(entry.path)

    def go_up(self):
        """Sobe um nível no diretório."""
        if self.mode == "sftp":
            # Linux path
            parent = "/".join(self.current_path.rstrip("/").split("/")[:-1]) or "/"
        else:
            # Windows path
            parent = os.path.dirname(self.current_path.rstrip("\\"))
            if not parent:
                parent = self.current_path
        self.navigate(parent)

    def confirm_selection(self):
        """Confirma a seleção e fecha a janela."""
        self.on_select(self.current_path)
        self.destroy()


class RestorePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=APP_BG)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── FORMULÁRIO ──
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 5))
        form.grid_columnconfigure((0, 1, 2, 3), weight=1)

        def fe(parent_frame, ph, show=None):
            return ctk.CTkEntry(parent_frame, placeholder_text=ph, show=show)

        # Row 0: Engine + Host + Porta
        self.engine = ctk.CTkOptionMenu(form, values=["PostgreSQL", "SQL Server"], command=self.toggle_engine)
        self.engine.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.host = fe(form, "Host")
        self.host.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.port = fe(form, "Porta")
        self.port.insert(0, "5432")
        self.port.grid(row=0, column=2, sticky="ew", padx=4, pady=4)

        # Row 1: User + Senha + Tipo (PG) + Database
        self.user = fe(form, "Usuário")
        self.user.insert(0, "PGADMIN")
        self.user.grid(row=1, column=0, sticky="ew", padx=4, pady=4)

        self.password = fe(form, "Senha", "*")
        self.password.grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        self.type = ctk.CTkOptionMenu(form, values=["normal", "upgrade"], command=self.toggle_type)
        self.type.grid(row=1, column=2, sticky="ew", padx=4, pady=4)

        self.database = ctk.CTkEntry(form, placeholder_text="Banco de destino")
        self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)

        # Row 2: Arquivo de backup
        self.file = ctk.CTkEntry(form, placeholder_text="Arquivo (.backup, .sql ou .bak)")
        self.file.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
        self.file_btn = ctk.CTkButton(form, text="Selecionar Arquivo", width=130, command=self.select_file)
        self.file_btn.grid(row=2, column=3, sticky="ew", padx=4, pady=4)

        # ── Sub-frame PG Upgrade (row 3) — usa self.host como SSH host ──
        self.upgrade_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.upgrade_frame.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.upgrade_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.ssh_user = fe(self.upgrade_frame, "SSH User")
        self.ssh_user.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.ssh_pass = fe(self.upgrade_frame, "SSH Password", "*")
        self.ssh_pass.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.old_version = fe(self.upgrade_frame, "Versão antiga (ex: 9.6)")
        self.old_version.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        self.new_version = fe(self.upgrade_frame, "Nova versão (ex: 16)")
        self.new_version.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        self.install_pg_var = ctk.BooleanVar(value=True)
        self.install_pg_check = ctk.CTkCheckBox(
            self.upgrade_frame, text="Instalar PostgreSQL no servidor",
            variable=self.install_pg_var
        )
        self.install_pg_check.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=4)

        # ── Sub-frame SQL Server transferência (row 3) ──
        self.transfer_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.transfer_frame.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.transfer_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.transfer_mode = ctk.CTkOptionMenu(self.transfer_frame,
                                               values=["Sem Transferência", "SFTP (Linux)", "SMB (Windows)"],
                                               command=self.toggle_transfer)
        self.transfer_mode.grid(row=0, column=0, sticky="ew", padx=4, pady=4)

        self.remote_restore_dir = ctk.CTkEntry(self.transfer_frame, placeholder_text="Diretório destino no servidor DB")
        self.remote_restore_dir.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4, pady=4)

        self.browse_remote_btn = ctk.CTkButton(self.transfer_frame, text="📂 Explorar", width=100, command=self.browse_remote_dir)
        self.browse_remote_btn.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        self.transfer_port = fe(self.transfer_frame, "Porta SSH")
        self.transfer_port.insert(0, "22")
        self.transfer_port.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self.transfer_user = fe(self.transfer_frame, "Usuário SSH")
        self.transfer_user.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self.transfer_password = fe(self.transfer_frame, "Senha SSH", "*")
        self.transfer_password.grid(row=1, column=2, columnspan=2, sticky="ew", padx=4, pady=4)

        self._sftp_widgets = [self.transfer_port, self.transfer_user, self.transfer_password]

        # ── BOTÕES ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(btn_frame, text="🔍 Listar Bases", command=self.listar_bases).grid(row=0, column=0, sticky="ew", padx=4)
        ctk.CTkButton(btn_frame, text="Executar Restore", command=self.start_restore).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(btn_frame, text="🗑️ Limpar Campos", fg_color="#475569", command=self.limpar_campos_restore).grid(row=0, column=2, sticky="ew", padx=4)
        self.cancel_btn = ctk.CTkButton(btn_frame, text="Cancelar", fg_color="#ef4444", command=cancel_process)
        self.cancel_btn.grid(row=0, column=3, sticky="ew", padx=4)

        # ── LOG ──
        self.log = ctk.CTkTextbox(self)
        self.log.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))

        # Estado inicial
        self.toggle_engine("PostgreSQL")

    def toggle_engine(self, value):
        """Alterna entre PostgreSQL e SQL Server."""
        if value == "SQL Server":
            self.port.delete(0, "end")
            self.port.insert(0, "1433")
            self.user.delete(0, "end")
            self.user.insert(0, "sa")
            self.type.grid_remove()
            self.upgrade_frame.grid_remove()
            self.database.grid(row=1, column=2, columnspan=2, sticky="ew", padx=4, pady=4)
            self.file.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
            self.file_btn.grid(row=2, column=3, sticky="ew", padx=4, pady=4)
            self.transfer_frame.grid(row=3, column=0, columnspan=4, sticky="ew")
            self.toggle_transfer(self.transfer_mode.get())
        else:
            self.port.delete(0, "end")
            self.port.insert(0, "5432")
            self.user.delete(0, "end")
            self.user.insert(0, "PGADMIN")
            self.type.grid(row=1, column=2, sticky="ew", padx=4, pady=4)
            self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)
            self.type.set("normal")
            self.toggle_type("normal")
            self.transfer_frame.grid_remove()

    def toggle_type(self, value):
        """PG: alterna entre normal e upgrade."""
        if value == "upgrade":
            self.database.grid_remove()
            self.file.grid_remove()
            self.file_btn.grid_remove()
            self.upgrade_frame.grid(row=3, column=0, columnspan=4, sticky="ew")
        else:
            self.database.grid(row=1, column=3, sticky="ew", padx=4, pady=4)
            self.file.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=4)
            self.file_btn.grid(row=2, column=3, sticky="ew", padx=4, pady=4)
            self.upgrade_frame.grid_remove()

    def toggle_transfer(self, value):
        """SQL Server: mostra/esconde campos SFTP e ajusta diretório padrão."""
        for w in self._sftp_widgets:
            w.grid_remove()
        self.remote_restore_dir.delete(0, "end")
        if "SFTP" in value:
            self.remote_restore_dir.insert(0, "/mnt/sdb/backup")
            self.transfer_port.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
            self.transfer_user.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
            self.transfer_password.grid(row=1, column=2, columnspan=2, sticky="ew", padx=4, pady=4)
        elif "SMB" in value:
            self.remote_restore_dir.insert(0, "C:\\Program Files\\Microsoft SQL Server\\MSSQL16.MSSQLSERVER\\MSSQL\\Backup")
        else:
            self.remote_restore_dir.insert(0, "C:\\Program Files\\Microsoft SQL Server\\MSSQL16.MSSQLSERVER\\MSSQL\\Backup")

    def browse_remote_dir(self):
        """Abre explorador remoto para selecionar diretório destino."""
        transfer_sel = self.transfer_mode.get()
        db_host = self.host.get()
        if not db_host:
            messagebox.showwarning("Atenção", "Preencha o Host do banco de dados primeiro.")
            return
        if "SFTP" in transfer_sel:
            user = self.transfer_user.get()
            password = self.transfer_password.get()
            port = int(self.transfer_port.get() or 22)
            if not all([user, password]):
                messagebox.showwarning("Atenção", "Preencha Usuário e Senha SSH para explorar.")
                return
            start_path = self.remote_restore_dir.get() or "/mnt/sdb/backup"
            RemoteBrowserWindow(self, mode="sftp", start_path=start_path,
                                ssh_host=db_host, ssh_user=user, ssh_password=password, ssh_port=port,
                                on_select=self._set_remote_dir)
        elif "SMB" in transfer_sel:
            remote_dir = self.remote_restore_dir.get()
            if len(remote_dir) >= 2 and remote_dir[1] == ":":
                drive_letter = remote_dir[0].lower()
                rest = remote_dir[2:]
                unc_path = f"\\\\{db_host}\\{drive_letter}${rest}"
            else:
                unc_path = f"\\\\{db_host}\\{remote_dir}"
            RemoteBrowserWindow(self, mode="smb", start_path=unc_path,
                                on_select=self._set_remote_dir_from_unc)
        else:
            path = filedialog.askdirectory()
            if path:
                self._set_remote_dir(path)

    def _set_remote_dir(self, path: str):
        self.remote_restore_dir.delete(0, "end")
        self.remote_restore_dir.insert(0, path)

    def _set_remote_dir_from_unc(self, unc_path: str):
        parts = unc_path.lstrip("\\").split("\\", 2)
        if len(parts) >= 2 and parts[1].endswith("$"):
            drive_letter = parts[1][0].upper()
            rest = parts[2] if len(parts) > 2 else ""
            local_path = f"{drive_letter}:\\{rest}"
        else:
            local_path = unc_path
        self.remote_restore_dir.delete(0, "end")
        self.remote_restore_dir.insert(0, local_path)

    def listar_bases(self):
        """Lista bases do servidor para facilitar a escolha do banco de destino."""
        engine = self.engine.get()
        host = self.host.get()
        port = self.port.get()
        user = self.user.get()
        password = self.password.get()

        if not host:
            messagebox.showwarning("Atenção", "Preencha o Host primeiro.")
            return

        def _fetch():
            try:
                if engine == "SQL Server":
                    bases = mssql_list_databases(host, port, user, password)
                else:
                    bases = pg_list_databases(host, port, user, password)
                nomes = [nome for nome, _ in bases]
                self.after(0, lambda: self._mostrar_bases(nomes))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erro", f"Não foi possível listar bases:\n{e}"))

        threading.Thread(target=_fetch, daemon=True).start()

    def _mostrar_bases(self, bases):
        """Mostra popup com as bases para o usuário selecionar."""
        if not bases:
            messagebox.showinfo("Bases", "Nenhuma base encontrada.")
            return

        win = ctk.CTkToplevel(self)
        win.title("Selecionar Base de Destino")
        win.geometry("350x400")
        win.configure(fg_color=APP_BG)
        win.transient(self)
        win.grab_set()

        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(win, text="Selecione o banco de destino:", font=("Arial", 13, "bold")).grid(row=0, column=0, pady=(10, 5), padx=10)

        lista = ctk.CTkScrollableFrame(win)
        lista.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        lista.grid_columnconfigure(0, weight=1)

        for i, nome in enumerate(bases):
            ctk.CTkButton(lista, text=nome, anchor="w", fg_color="transparent", hover_color="#334155",
                          command=lambda n=nome: self._selecionar_base(n, win)).grid(row=i, column=0, sticky="ew", pady=1)

    def _selecionar_base(self, nome, win):
        """Preenche o campo database e fecha a janela."""
        self.database.delete(0, "end")
        self.database.insert(0, nome)
        win.destroy()

    def limpar_campos_restore(self):
        self.host.delete(0, "end")
        self.database.delete(0, "end")
        self.file.delete(0, "end")
        self.ssh_user.delete(0, "end")
        self.ssh_pass.delete(0, "end")
        self.old_version.delete(0, "end")
        self.new_version.delete(0, "end")
        self.transfer_user.delete(0, "end")
        self.transfer_password.delete(0, "end")

    def select_file(self):
        engine = self.engine.get()
        if engine == "SQL Server":
            filetypes = [("Arquivos SQL Server", "*.bak"), ("Todos os arquivos", "*.*")]
        else:
            filetypes = [("Arquivos de Banco de Dados", "*.backup *.backup_postgresql *.sql"),
                         ("Todos os arquivos", "*.*")]
        path = filedialog.askopenfilename(title="Selecione o arquivo de Backup", filetypes=filetypes)
        if path:
            self.file.delete(0, "end")
            self.file.insert(0, path)

    def start_restore(self):
        engine = self.engine.get()
        if not self.host.get().strip():
            messagebox.showwarning("Atenção", "Preencha o Host.")
            return
        if engine == "SQL Server":
            self._start_restore_mssql()
        else:
            self._start_restore_pg()

    def _start_restore_pg(self):
        data = {
            "host": self.host.get(),
            "port": self.port.get(),
            "user": self.user.get(),
            "password": self.password.get(),
            "restore_type": self.type.get()
        }
        if data["restore_type"] == "normal":
            if not self.database.get().strip():
                messagebox.showwarning("Atenção", "Preencha o nome do banco de destino.")
                return
            if not self.file.get().strip():
                messagebox.showwarning("Atenção", "Selecione o arquivo de backup.")
                return
            data.update({"database": self.database.get(), "backupfile": self.file.get()})
        else:
            data.update({
                "ssh_host": self.host.get(),
                "ssh_user": self.ssh_user.get(),
                "ssh_password": self.ssh_pass.get(),
                "old_version": self.old_version.get(),
                "new_version": self.new_version.get(),
                "install_pg": self.install_pg_var.get(),
            })
        threading.Thread(target=run_restore, args=(data,), daemon=True).start()

    def _start_restore_mssql(self):
        if not self.database.get().strip():
            messagebox.showwarning("Atenção", "Preencha o nome do banco de destino.")
            return
        if not self.file.get().strip():
            messagebox.showwarning("Atenção", "Selecione o arquivo .bak.")
            return
        transfer_sel = self.transfer_mode.get()
        data = {
            "host": self.host.get(),
            "port": self.port.get(),
            "user": self.user.get(),
            "password": self.password.get(),
            "database": self.database.get(),
            "backupfile": self.file.get(),
            "remote_restore_dir": self.remote_restore_dir.get(),
        }
        if "SFTP" in transfer_sel:
            if not self.transfer_user.get().strip() or not self.transfer_password.get().strip():
                messagebox.showwarning("Atenção", "Preencha Usuário e Senha SSH para transferir o arquivo.")
                return
            data["transfer_mode"] = "sftp"
            data["transfer_port"] = self.transfer_port.get()
            data["transfer_user"] = self.transfer_user.get()
            data["transfer_password"] = self.transfer_password.get()
        elif "SMB" in transfer_sel:
            data["transfer_mode"] = "smb"
        else:
            data["transfer_mode"] = "none"
        threading.Thread(target=run_restore_mssql, args=(data,), daemon=True).start()

    def update_log(self):
        log = get_log()
        if len(log) != getattr(self, '_last_log_len', -1):
            self._last_log_len = len(log)
            self.log.delete("0.0", "end")
            self.log.insert("0.0", "".join(log))
        self.cancel_btn.configure(state="normal" if is_running() else "disabled")


if __name__ == "__main__":
    init_db()
    app = App()
    app.mainloop()