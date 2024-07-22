import shutil
import sys
import os
import json
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel, QListWidget, \
    QMessageBox, QFileDialog, QMenuBar, QAction, QMainWindow, QTextEdit, QProgressBar, QComboBox, QInputDialog
from PyQt5.QtCore import Qt, QProcess, QFileSystemWatcher, QThread, pyqtSignal, QTimer
import git

SETTINGS_FILE = 'settings.json'


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"projects_dir": "C:/"}


def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)


class OutputWindow(QWidget):
    def __init__(self, project_name, process):
        super().__init__()
        self.setWindowTitle(f"{project_name}")
        self.layout = QVBoxLayout()
        self.process = process

        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        self.layout.addWidget(self.output_text)

        self.status_label = QLabel("Проект запущен...", self)
        self.layout.addWidget(self.status_label)

        self.setLayout(self.layout)

    def append_output(self, text):
        self.output_text.append(text)

    def set_status(self, status):
        self.status_label.setText(status)

    def closeEvent(self, event):
        if self.process and self.process.state() == QProcess.Running:
            self.process.terminate()
            self.process.waitForFinished(3000)
            if self.process.state() == QProcess.Running:
                self.process.kill()
        event.accept()


class SettingsWindow(QWidget):
    def __init__(self, parent):
        super(SettingsWindow, self).__init__()
        self.parent = parent
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        self.path_label = QLabel("Путь папки проектов:", self)
        layout.addWidget(self.path_label)

        self.path_input = QLineEdit(self)
        self.path_input.setText(self.parent.projects_dir)
        layout.addWidget(self.path_input)

        self.path_browse_button = QPushButton("Обзор...", self)
        self.path_browse_button.clicked.connect(self.browse_folder)
        layout.addWidget(self.path_browse_button)

        self.run_files_label = QLabel("Сбросить пути файлов запуска:", self)
        layout.addWidget(self.run_files_label)

        self.run_files_reset_button = QPushButton("Сбросить", self)
        self.run_files_reset_button.clicked.connect(self.reset_run_paths)
        layout.addWidget(self.run_files_reset_button)

        self.save_button = QPushButton("Сохранить", self)
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)

        self.setLayout(layout)
        self.setWindowTitle('Настройки')

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку проектов", self.parent.projects_dir)
        if folder:
            self.path_input.setText(folder)

    def reset_run_paths(self):
        for project in os.listdir(self.parent.projects_dir):
            config_path = os.path.join(self.parent.projects_dir, project, 'config.json')
            if os.path.exists(config_path):
                os.remove(config_path)
        QMessageBox.information(self, "Сброс путей", "Пути файлов запуска сброшены")

    def save_settings(self):
        new_path = self.path_input.text()
        if new_path and new_path != self.parent.projects_dir:
            self.parent.projects_dir = new_path
            os.makedirs(self.parent.projects_dir, exist_ok=True)
            self.parent.load_projects()
            self.parent.file_watcher.addPath(new_path)
            settings = load_settings()
            settings['projects_dir'] = new_path
            save_settings(settings)
        self.close()


class CloneThread(QThread):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url, projects_dir):
        super().__init__()
        self.url = url
        self.projects_dir = projects_dir

    def run(self):
        try:
            repo_name = self.url.split('/')[-1].replace(".git", "")
            project_path = os.path.join(self.projects_dir, repo_name)
            self.message.emit(f"Скачивание проекта {repo_name}...")
            git.Repo.clone_from(self.url, project_path)

            self.progress.emit(35)
            self.message.emit("Создание виртуального окружения...")
            subprocess.check_call([sys.executable, '-m', 'venv', self.get_venv(project_path)])

            self.progress.emit(60)
            requirements_path = os.path.join(project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                self.message.emit("Установка зависимостей...")
                subprocess.check_call(
                    [os.path.join(self.get_venv(project_path), 'Scripts', 'pip'), 'install', '-r', requirements_path])

            self.progress.emit(100)
        except Exception as e:
            self.message.emit(str(e))
        self.finished.emit()

    def get_venv(self, project_path):
        venv_path = os.path.join(project_path, 'venv')
        if os.path.exists(venv_path):
            return venv_path
        return os.path.join(project_path, '.venv')


class UpdateThread(QThread):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, project_path):
        super().__init__()
        self.project_path = project_path

    def run(self):
        try:
            self.message.emit("Обновление проекта...")
            repo = git.Repo(self.project_path)
            origin = repo.remotes.origin
            origin.pull()

            self.progress.emit(50)
            requirements_path = os.path.join(self.project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                self.message.emit("Обновление зависимостей...")
                subprocess.check_call(
                    [os.path.join(self.get_venv(self.project_path), 'Scripts', 'pip'), 'install', '-r', requirements_path])

            self.progress.emit(100)
        except Exception as e:
            self.message.emit(str(e))
        self.finished.emit()

    def get_venv(self, project_path):
        venv_path = os.path.join(project_path, 'venv')
        if os.path.exists(venv_path):
            return venv_path
        return os.path.join(project_path, '.venv')


class GitHubManager(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = load_settings()
        self.projects_dir = self.settings['projects_dir']
        os.makedirs(self.projects_dir, exist_ok=True)
        self.output_windows = {}

        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.addPath(self.projects_dir)
        self.file_watcher.directoryChanged.connect(self.load_projects)

        self.initUI()
        self.autoupdate_projects()

    def autoupdate_projects(self):
        self.show_progress("Автообновление проектов...", 0)
        total_projects = len(os.listdir(self.projects_dir))
        progress_step = 100 // total_projects if total_projects else 100

        for idx, project in enumerate(os.listdir(self.projects_dir)):
            project_path = os.path.join(self.projects_dir, project)
            self.update_single_project(project_path)
            self.progress_bar.setValue((idx + 1) * progress_step)

        self.status_label.setText("Автообновление завершено.")
        QTimer.singleShot(2000, self.hide_progress)

    def update_single_project(self, project_path):
        try:
            repo = git.Repo(project_path)
            origin = repo.remotes.origin
            origin.pull()

            requirements_path = os.path.join(project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                subprocess.check_call(
                    [os.path.join(self.get_venv(project_path), 'Scripts', 'pip'), 'install', '-r', requirements_path])
        except Exception as e:
            print(f"Ошибка при обновлении проекта {project_path}: {e}")

    def initUI(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        menu_bar = self.menuBar()

        self.settings_action = QAction("Настройки", self)
        self.settings_action.triggered.connect(self.open_settings)
        menu_bar.addAction(self.settings_action)

        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("Введите ссылку на GitHub")
        main_layout.addWidget(self.url_input)

        self.clone_button = QPushButton("Клонировать проект", self)
        self.clone_button.clicked.connect(self.clone_project)
        main_layout.addWidget(self.clone_button)

        self.update_button = QPushButton("Обновить проект", self)
        self.update_button.clicked.connect(self.update_project)
        main_layout.addWidget(self.update_button)

        self.run_button = QPushButton("Запустить проект", self)
        self.run_button.clicked.connect(self.run_project)
        main_layout.addWidget(self.run_button)

        self.switch_commit_button = QPushButton("Переключить коммит", self)
        self.switch_commit_button.clicked.connect(self.switch_commit)
        main_layout.addWidget(self.switch_commit_button)

        self.commit_selector = QComboBox(self)
        self.commit_selector.setVisible(False)
        main_layout.addWidget(self.commit_selector)

        self.projects_list = QListWidget(self)
        self.projects_list.currentItemChanged.connect(self.update_commits)
        self.load_projects()
        main_layout.addWidget(self.projects_list)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("", self)
        self.status_label.setVisible(False)
        main_layout.addWidget(self.status_label)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        self.setWindowTitle('Scripts Manager')

        self.show()

    def load_projects(self):
        self.projects_list.clear()
        for project in os.listdir(self.projects_dir):
            self.projects_list.addItem(project)
        self.update_commits()

    def show_progress(self, message, value=0):
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(True)
        self.status_label.setText(message)
        self.status_label.setVisible(True)

    def hide_progress(self):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

    def clone_project(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Введите ссылку на GitHub")
            return

        self.show_progress("Начало клонирования...")

        self.clone_thread = CloneThread(url, self.projects_dir)
        self.clone_thread.progress.connect(self.progress_bar.setValue)
        self.clone_thread.message.connect(self.status_label.setText)
        self.clone_thread.finished.connect(self.on_clone_finished)
        self.clone_thread.start()

    def on_clone_finished(self):
        self.load_projects()
        self.hide_progress()

    def update_project(self):
        selected_item = self.projects_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Ошибка", "Выберите проект для обновления")
            return

        project_path = os.path.join(self.projects_dir, selected_item.text())
        self.show_progress("Начало обновления...", 0)

        try:
            repo = git.Repo(project_path)
            if repo.is_dirty():
                reply = QMessageBox.question(self, "Несохраненные изменения",
                                             "Есть несохраненные изменения. Сохранить изменения перед обновлением?",
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    repo.git.add(A=True)
                    repo.index.commit("Сохранение незакоммиченных изменений перед обновлением")

            origin = repo.remotes.origin
            origin.pull()

            requirements_path = os.path.join(project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                subprocess.check_call(
                    [os.path.join(self.get_venv(project_path), 'Scripts', 'pip'), 'install', '-r', requirements_path])

            self.status_label.setText("Обновление завершено.")
            QTimer.singleShot(2000, self.hide_progress)

        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Ошибка при обновлении проекта: {e}")
            self.hide_progress()

    def on_update_finished(self):
        # После завершения обновления переключаемся на последний коммит
        selected_item = self.projects_list.currentItem()
        if selected_item:
            project_path = os.path.join(self.projects_dir, selected_item.text())
            try:
                repo = git.Repo(project_path)
                latest_commit = repo.heads.master.commit.hexsha  # Предполагается, что главная ветка называется master
                repo.git.checkout(latest_commit)
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Ошибка при переключении на последний коммит: {e}")

        self.status_label.setText("Обновление завершено.")
        QTimer.singleShot(2000, self.hide_progress)

    def run_project(self):
        selected_item = self.projects_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Ошибка", "Выберите проект для запуска")
            return

        project_name = selected_item.text()
        project_path = os.path.join(self.projects_dir, project_name)
        config_path = os.path.join(project_path, 'config.json')

        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            run_file = config.get('run_file')
        else:
            run_file = None

        if not run_file:
            run_file, _ = QFileDialog.getOpenFileName(self, "Выберите файл для запуска", project_path,
                                                      "Python Files (*.py);;All Files (*)")
            if not run_file:
                QMessageBox.warning(self, "Ошибка", "Файл запуска не выбран")
                return

            with open(config_path, 'w') as f:
                json.dump({'run_file': run_file}, f)

        python_executable = os.path.join(self.get_venv(project_path), 'Scripts', 'python.exe')

        if not os.path.exists(python_executable):
            QMessageBox.critical(self, "Ошибка", f"Не найден интерпретатор Python: {python_executable}")
            return

        if not os.path.exists(run_file):
            QMessageBox.critical(self, "Ошибка", f"Не найден файл запуска: {run_file}")
            return

        self.show_progress(f"Запуск {project_name}...", 0)

        process = QProcess(self)
        process.setProgram(python_executable)
        process.setArguments([run_file])
        process.setWorkingDirectory(project_path)

        self.output_windows[project_name] = OutputWindow(project_name, process)
        self.output_windows[project_name].show()

        process.readyReadStandardOutput.connect(lambda: self.output_windows[project_name].append_output(str(process.readAllStandardOutput(), 'utf-8')))
        process.readyReadStandardError.connect(lambda: self.output_windows[project_name].append_output(str(process.readAllStandardError(), 'utf-8')))
        process.finished.connect(lambda: self.output_windows[project_name].set_status("Скрипт завершил работу"))

        process.start()
        self.hide_progress()

    def open_settings(self):
        self.settings = SettingsWindow(self)
        self.settings.show()

    def switch_commit(self):
        current_item = self.projects_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите проект для переключения коммита")
            return

        selected_commit = self.commit_selector.currentText().split(" - ")[0]
        project_name = current_item.text()
        project_path = os.path.join(self.projects_dir, project_name)

        try:
            repo = git.Repo(project_path)

            # Проверка на незакоммиченные изменения
            if repo.is_dirty():
                QMessageBox.warning(self, "Ошибка",
                                    "Есть несохраненные изменения. Сохраните изменения перед переключением коммитов.")
                return

            # Проверка наличия выбранного коммита
            try:
                commit = repo.commit(selected_commit)  # Проверка наличия коммита
            except git.exc.BadName:
                QMessageBox.warning(self, "Ошибка", f"Коммит {selected_commit} не найден в репозитории.")
                return

            # Переключение на выбранный коммит
            repo.git.checkout(selected_commit)

            # Удаление старого виртуального окружения
            venv_path = self.get_venv(project_path)
            if os.path.exists(venv_path):
                shutil.rmtree(venv_path)

            # Создание нового виртуального окружения и установка зависимостей
            subprocess.check_call([sys.executable, '-m', 'venv', venv_path])
            requirements_path = os.path.join(project_path, 'requirements.txt')
            if os.path.exists(requirements_path):
                subprocess.check_call([os.path.join(venv_path, 'Scripts', 'pip'), 'install', '-r', requirements_path])

            # Обновление видимости коммитов после переключения
            self.update_commits()

            QMessageBox.information(self, "Успех", f"Переключено на коммит {selected_commit}")

        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Ошибка при переключении коммита: {e}")

    def update_commits(self):
        self.commit_selector.clear()
        self.commit_selector.setVisible(False)

        selected_item = self.projects_list.currentItem()
        if not selected_item:
            return

        project_name = selected_item.text()
        project_path = os.path.join(self.projects_dir, project_name)
        config_path = os.path.join(project_path, 'config.json')

        try:
            repo = git.Repo(project_path)
            # Получаем все коммиты
            commits = list(repo.iter_commits('--all'))
            commit_info = []

            for commit in commits:
                self.commit_selector.addItem(f"{commit.hexsha[:7]} - {commit.message.strip()[:50]}")
                commit_info.append({"hash": commit.hexsha, "message": commit.message.strip()})

            # Сохраняем информацию о коммитах в config.json
            with open(config_path, 'w') as f:
                json.dump({"commits": commit_info}, f)

            if commits:
                self.commit_selector.setVisible(True)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить коммиты: {str(e)}")

    def get_venv(self, project_path):
        venv_path = os.path.join(project_path, 'venv')
        if os.path.exists(venv_path):
            return venv_path
        return os.path.join(project_path, '.venv')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DisableWindowContextHelpButton, False)
    ex = GitHubManager()
    sys.exit(app.exec_())
