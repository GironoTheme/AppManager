import asyncio
import os
import sys
import json
import shutil
import subprocess
import threading
import git
from tkinter import Tk, Frame, Label, Entry, Button, Listbox, Menu, filedialog, messagebox, simpledialog, Scrollbar, Text, Toplevel, END, BOTH, W, N, E, S, HORIZONTAL, X, OptionMenu, StringVar
from tkinter.ttk import Progressbar, Style, Treeview

from pynput import keyboard

SETTINGS_FILE = 'settings.json'


def get_python_executable():
    if hasattr(sys, 'frozen'):
        with open(os.path.join(sys._MEIPASS, 'python_path.txt'), 'r') as f:
            return f.read().strip()
    else:
        return sys.executable


async def create_venv(project_path):
    venv_path = os.path.join(project_path, 'venv')
    python_executable = get_python_executable()  # Используем сохраненный путь к Python
    venv_create_command = [python_executable, '-m', 'venv', venv_path]

    # Проверяем, что python_executable существует
    if not os.path.exists(python_executable):
        raise Exception(f"Python executable not found: {python_executable}")

    print(f"Creating virtual environment with: {venv_create_command}")

    # Создание виртуального окружения
    proc = await asyncio.create_subprocess_exec(
        *venv_create_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise Exception(f"Error creating virtual environment: {stderr.decode()}")

    requirements_path = os.path.join(project_path, 'requirements.txt')
    if os.path.exists(requirements_path):
        pip_executable = os.path.join(venv_path, 'Scripts', 'pip')
        install_command = [pip_executable, 'install', '-r', requirements_path]

        # Проверяем, что pip_executable существует
        if not os.path.exists(pip_executable):
            raise Exception(f"Pip executable not found: {pip_executable}")

        print(f"Installing dependencies with: {install_command}")

        # Установка зависимостей
        proc = await asyncio.create_subprocess_exec(
            *install_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise Exception(f"Error installing dependencies: {stderr.decode()}")

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"projects_dir": "C:/"}


def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)


class OutputWindow(Toplevel):
    def __init__(self, project_name, process):
        super().__init__()
        self.title(f"{project_name}")
        self.process = process

        self.output_text = Text(self, state='disabled')
        self.output_text.pack(expand=True, fill=BOTH)

        self.status_label = Label(self, text="Проект запущен...")
        self.status_label.pack()

        self.stop_button = Button(self, text="Остановить", command=self.stop_process)
        self.stop_button.pack()

    def append_output(self, text):
        self.output_text.config(state='normal')
        self.output_text.insert(END, text)
        self.output_text.config(state='disabled')

    def set_status(self, status):
        self.status_label.config(text=status)

    def stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.set_status("Проект остановлен")
            self.stop_button.config(state='disabled')

    def close(self):
        self.stop_process()
        self.destroy()


class SettingsWindow(Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.initUI()

    def initUI(self):
        self.title("Настройки")
        self.geometry("400x200")

        style = Style(self)
        style.configure("TLabel", font=("Segoe UI", 12))
        style.configure("TButton", font=("Segoe UI", 12))

        path_label = Label(self, text="Путь папки проектов:")
        path_label.pack(pady=10)

        self.path_input = Entry(self)
        self.path_input.insert(0, self.parent.projects_dir)
        self.path_input.pack(padx=10, pady=5)

        self.path_browse_button = Button(self, text="Обзор...", command=self.browse_folder)
        self.path_browse_button.pack(pady=5)

        self.save_button = Button(self, text="Сохранить", command=self.save_settings)
        self.save_button.pack(pady=10)

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.parent.projects_dir, title="Выберите папку проектов")
        if folder:
            self.path_input.delete(0, END)
            self.path_input.insert(0, folder)

    def save_settings(self):
        new_path = self.path_input.get()
        if new_path and new_path != self.parent.projects_dir:
            self.parent.projects_dir = new_path
            os.makedirs(self.parent.projects_dir, exist_ok=True)
            self.parent.load_projects()
            settings = self.parent.load_settings()
            settings['projects_dir'] = new_path
            self.parent.save_settings(settings)
        self.destroy()

    def close(self):
        self.destroy()


class CloneThread(threading.Thread):
    def __init__(self, url, projects_dir, progress_callback, message_callback, finished_callback):
        super().__init__()
        self.url = url
        self.projects_dir = projects_dir
        self.progress_callback = progress_callback
        self.message_callback = message_callback
        self.finished_callback = finished_callback

    def run(self):
        asyncio.run(self.clone_project())

    async def clone_project(self):
        try:
            repo_name = self.url.split('/')[-1].replace(".git", "")
            project_path = os.path.join(self.projects_dir, repo_name)
            if os.path.exists(project_path):
                raise Exception(f"Проект {repo_name} уже существует.")

            self.message_callback(f"Скачивание проекта {repo_name}...")
            git.Repo.clone_from(self.url, project_path)

            self.progress_callback(35)
            self.message_callback("Создание виртуального окружения...")

            await create_venv(project_path)

            self.progress_callback(100)
        except Exception as e:
            self.message_callback(str(e))
        self.finished_callback()


class UpdateThread(threading.Thread):
    def __init__(self, project_path, progress_callback, message_callback, finished_callback):
        super().__init__()
        self.project_path = project_path
        self.progress_callback = progress_callback
        self.message_callback = message_callback
        self.finished_callback = finished_callback

    def run(self):
        try:
            self.message_callback("Обновление проекта...")
            repo = git.Repo(self.project_path)
            origin = repo.remotes.origin
            origin.pull()

            self.progress_callback(50)
            requirements_path = os.path.join(self.project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                self.message_callback("Обновление зависимостей...")
                subprocess.run(
                    [os.path.join(self.get_venv(self.project_path), 'Scripts', 'pip'), 'install', '-r',
                     requirements_path],
                    check=True)

            self.progress_callback(100)
        except Exception as e:
            self.message_callback(str(e))
        self.finished_callback()

    def get_venv(self, project_path):
        venv_path = os.path.join(project_path, 'venv')
        if os.path.exists(venv_path):
            return venv_path
        return os.path.join(project_path, '.venv')


class GitHubManager(Tk):
    def __init__(self):
        super().__init__()

        self.settings = load_settings()
        self.projects_dir = self.settings['projects_dir']
        os.makedirs(self.projects_dir, exist_ok=True)
        self.output_windows = {}
        self.selected_commit = StringVar()

        self.initUI()
        self.autoupdate_projects()

        self.minsize(800, 600)

        self.protocol("WM_DELETE_WINDOW", self.on_close)  # Обработчик закрытия окна

        self.listener = keyboard.GlobalHotKeys({
            '<ctrl>+<alt>+q': self.stop_last_project
        })
        self.listener.start()

    def stop_last_project(self):
        print("Hotkey triggered: Ctrl+Alt+Q")  # Проверка, вызывается ли функция
        if self.output_windows:
            last_project = list(self.output_windows.keys())[-1]
            print(f"Stopping project: {last_project}")  # Проверка, что проект выбирается
            self.output_windows[last_project].stop_process()
        else:
            print("No projects running")

    def on_close(self):
        for output_window in self.output_windows.values():
            output_window.stop_process()
        self.destroy()

    def switch_commit(self, project_path):
        selected_item = self.commit_tree.selection()
        if not selected_item:
            messagebox.showwarning("Ошибка", "Пожалуйста, выберите коммит для переключения.")
            return

        selected_commit = self.commit_tree.item(selected_item[0], "values")[0]

        try:
            repo = git.Repo(project_path)

            # Проверка на незакоммиченные изменения
            if repo.is_dirty():
                messagebox.showwarning("Ошибка",
                                       "Есть несохраненные изменения. Сохраните изменения перед переключением коммитов.")
                return

            # Проверка наличия выбранного коммита
            try:
                repo.git.checkout(selected_commit)
                messagebox.showinfo("Успех", f"Переключено на коммит {selected_commit}.")
            except git.exc.BadName:
                messagebox.showerror("Ошибка", f"Коммит с SHA {selected_commit} не найден.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось переключиться на коммит: {str(e)}")

    def show_commits_window(self):
        selected_project = self.projects_listbox.get(self.projects_listbox.curselection())
        project_path = os.path.join(self.projects_dir, selected_project)

        # Создание нового окна
        self.commits_window = Toplevel(self)
        self.commits_window.title(f"Коммиты: {selected_project}")
        self.commits_window.geometry("600x400")  # Размер окна

        # Настройка стиля
        style = Style(self.commits_window)
        style.configure("Treeview", rowheight=25, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 12, "bold"))

        # Заголовок
        title_label = Label(self.commits_window, text=f"Коммиты проекта {selected_project}", font=("Arial", 14))
        title_label.pack(pady=10)

        # Рамка для таблицы коммитов
        commits_frame = Frame(self.commits_window)
        commits_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Scrollbar для таблицы
        scrollbar = Scrollbar(commits_frame)
        scrollbar.pack(side="right", fill="y")

        # Таблица для отображения коммитов
        self.commit_tree = Treeview(commits_frame, columns=("sha", "message"), show="headings", yscrollcommand=scrollbar.set)
        self.commit_tree.pack(fill="both", expand=True)

        scrollbar.config(command=self.commit_tree.yview)

        # Определение столбцов
        self.commit_tree.heading("sha", text="SHA")
        self.commit_tree.heading("message", text="Сообщение")

        self.commit_tree.column("sha", width=150)
        self.commit_tree.column("message", width=400)

        # Загрузка коммитов в таблицу
        self.update_commits(project_path)

        # Кнопка для переключения на выбранный коммит
        switch_button = Button(self.commits_window, text="Переключиться на выбранный коммит",
                               command=lambda: self.switch_commit(project_path))
        switch_button.pack(pady=10)

    def update_commits(self, project_path):
        try:
            repo = git.Repo(project_path)
            commits = list(repo.iter_commits('master', max_count=100))
            self.commit_tree.delete(*self.commit_tree.get_children())  # Очистка предыдущих данных

            for commit in commits:
                self.commit_tree.insert("", "end", values=(commit.hexsha[:7], commit.message))
            if commits:
                self.commit_tree.selection_set(self.commit_tree.get_children()[0])  # Выбор первого коммита
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить коммиты: {str(e)}")

    def initUI(self):
        self.title("GitHub Manager")

        self.menubar = Menu(self)
        self.config(menu=self.menubar)

        fileMenu = Menu(self.menubar, tearoff=0)
        fileMenu.add_command(label="Настройки", command=self.show_settings)
        fileMenu.add_command(label="Выйти", command=self.on_close)
        self.menubar.add_cascade(label="Файл", menu=fileMenu)

        projectMenu = Menu(self.menubar, tearoff=0)
        projectMenu.add_command(label="Скачать проект", command=self.clone_project)
        self.menubar.add_cascade(label="Проекты", menu=projectMenu)

        self.frame = Frame(self)
        self.frame.pack(fill=BOTH, expand=True)

        self.projects_listbox = Listbox(self.frame)
        self.projects_listbox.pack(side="left", fill=BOTH, expand=True)

        scrollbar = Scrollbar(self.frame)
        scrollbar.pack(side="left", fill='y')
        self.projects_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.projects_listbox.yview)

        self.projects_listbox.bind('<<ListboxSelect>>', self.on_project_select)

        self.details_frame = Frame(self.frame)
        self.details_frame.pack(fill=BOTH, expand=True)

        self.project_label = Label(self.details_frame, text="")
        self.project_label.pack()

        self.run_button = Button(self.details_frame, text="Запустить проект", command=self.run_project)
        self.run_button.pack()

        self.commits_button = Button(self.details_frame, text="Переключить коммит", command=self.show_commits_window)
        self.commits_button.pack()

        self.update_button = Button(self.details_frame, text="Обновить проект", command=self.update_project)
        self.update_button.pack()

        self.delete_button = Button(self.details_frame, text="Удалить проект", command=self.delete_project)
        self.delete_button.pack()

        self.progress_bar = Progressbar(self.details_frame, orient=HORIZONTAL, length=100, mode='determinate')
        self.progress_bar.pack(fill=X, padx=10, pady=10)

        self.progress_label = Label(self.details_frame, text="")
        self.progress_label.pack()

        self.load_projects()

    def show_settings(self):
        settings_window = SettingsWindow(self)
        settings_window.grab_set()

    def load_projects(self):
        self.projects_listbox.delete(0, END)
        if os.path.exists(self.projects_dir):
            for project in os.listdir(self.projects_dir):
                project_path = os.path.join(self.projects_dir, project)
                if os.path.isdir(project_path) and os.path.exists(os.path.join(project_path, '.git')):
                    self.projects_listbox.insert(END, project)

    def on_project_select(self, event):
        if self.projects_listbox.curselection():
            selected_project = self.projects_listbox.get(self.projects_listbox.curselection())
            self.project_label.config(text=f"Проект: {selected_project}")

    def run_project(self):
        selected_project = self.projects_listbox.get(self.projects_listbox.curselection())
        project_path = os.path.join(self.projects_dir, selected_project)

        config_path = os.path.join(project_path, 'config.json')

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except FileNotFoundError:
            config = {}  # Инициализация переменной config
            run_file = filedialog.askopenfilename(initialdir=project_path, title="Выберите файл для запуска")
            if run_file:
                config['run_file'] = run_file
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
            else:
                messagebox.showerror("Ошибка", "Файл для запуска не выбран.")
                return

        run_file = config['run_file']

        self.output_windows[selected_project] = OutputWindow(selected_project, None)
        self.output_windows[selected_project].append_output(f"Запуск {run_file}...\n")

        venv_path = os.path.join(project_path, 'venv', 'Scripts', 'python.exe')
        if not os.path.exists(venv_path):
            venv_path = os.path.join(project_path, '.venv', 'Scripts', 'python.exe')

        if not os.path.exists(venv_path):
            messagebox.showerror("Ошибка", "Виртуальное окружение не найдено.")
            return

        process = subprocess.Popen([venv_path, run_file], cwd=project_path, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.output_windows[selected_project].process = process

        def read_output():
            for line in process.stdout:
                self.output_windows[selected_project].append_output(line)
            process.stdout.close()

            for line in process.stderr:
                self.output_windows[selected_project].append_output(line)
            process.stderr.close()

            process.wait()
            self.output_windows[selected_project].set_status("Проект завершен")

        threading.Thread(target=read_output).start()

    def update_project(self):
        selected_project = self.projects_listbox.get(self.projects_listbox.curselection())
        project_path = os.path.join(self.projects_dir, selected_project)

        def update_progress(value):
            self.progress_bar['value'] = value

        def update_message(message):
            self.progress_label.config(text=message)

        def update_finished():
            messagebox.showinfo("Обновление", "Проект успешно обновлен")
            self.progress_bar['value'] = 0
            self.progress_label.config(text="")

        update_thread = UpdateThread(project_path, update_progress, update_message, update_finished)
        update_thread.start()

    def update_project_by_path(self, project_path):
        def update_progress(value):
            self.progress_bar['value'] = value

        def update_message(message):
            self.progress_label.config(text=message)

        def update_finished():
            self.progress_bar['value'] = 0
            self.progress_label.config(text="")

        update_thread = UpdateThread(project_path, update_progress, update_message, update_finished)
        update_thread.start()

    def delete_project(self):
        selected_project = self.projects_listbox.get(self.projects_listbox.curselection())
        project_path = os.path.join(self.projects_dir, selected_project)

        confirm = messagebox.askyesno("Удалить проект", f"Вы уверены, что хотите удалить проект {selected_project}?")
        if confirm:
            shutil.rmtree(project_path)
            self.load_projects()

    def clone_project(self):
        url = simpledialog.askstring("Скачать проект", "Введите URL репозитория GitHub")
        if url:
            def update_progress(value):
                self.progress_bar['value'] = value

            def update_message(message):
                self.progress_label.config(text=message)

            def update_finished():
                self.load_projects()
                messagebox.showinfo("Скачивание", "Проект успешно скачан")
                self.progress_bar['value'] = 0
                self.progress_label.config(text="")

            clone_thread = CloneThread(url, self.projects_dir, update_progress, update_message, update_finished)
            clone_thread.start()

    def autoupdate_projects(self):
        for project in os.listdir(self.projects_dir):
            project_path = os.path.join(self.projects_dir, project)
            if os.path.isdir(project_path) and os.path.exists(os.path.join(project_path, '.git')):
                self.update_project_by_path(project_path)
        self.after(3600000, self.autoupdate_projects)  # Повторный вызов функции через 1 час


if __name__ == "__main__":
    app = GitHubManager()
    app.mainloop()
