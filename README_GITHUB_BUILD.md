# Mecatech Pointage — GitHub push and Windows EXE build

This project is configured so GitHub Actions builds the Windows `.exe` and the Inno Setup installer automatically.

## A. Push this version to your repository

Open Terminal on your Mac and enter the folder containing this project.

If this folder is **not** a Git repository yet:

```bash
cd /path/to/MecatechPointage
git init
git branch -M main
git remote add origin https://github.com/ibrahimatia99/mecatech-pointage.git
git add .
git commit -m "Release Mecatech Pointage v2.2.3"
git push -u origin main
```

If it is already a Git repository:

```bash
cd /path/to/MecatechPointage
git remote -v
git status
git add .
git commit -m "Release Mecatech Pointage v2.2.3"
git push origin main
```

If `origin` is wrong:

```bash
git remote set-url origin https://github.com/ibrahimatia99/mecatech-pointage.git
```

When GitHub asks for authentication, use your normal GitHub credential/token method. Do not put a token directly into source files.

## B. Start the Windows build

The workflow file is already included:

```text
.github/workflows/build-windows.yml
```

It runs on a GitHub-hosted Windows machine and performs these steps automatically:

1. Checks out the repository.
2. Installs Python 3.12.
3. Installs `requirements.txt`.
4. Compiles the Python sources and runs the backend/frontend/ESP regression tests.
5. Builds `MecatechPointage.exe` with PyInstaller.
6. Installs Inno Setup.
7. Creates `MecatechPointage-Setup-2.2.3.exe`.
8. Uploads the portable application folder and installer as workflow artifacts.

After pushing to `main`, open your repository on GitHub → **Actions** → **Build Mecatech Pointage - Windows**. Open the newest run. Wait for the job to finish successfully. In the run page, download the **MecatechPointage-Windows** artifact.

Inside it you will find:

```text
dist/MecatechPointage/
    MecatechPointage.exe

installer/
    MecatechPointage-Setup-2.2.3.exe
```

For normal customer installation, use the `MecatechPointage-Setup-2.2.3.exe` installer.

## C. Build locally on Windows

Install Python 3.12, then from PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python -m PyInstaller --noconfirm --clean MecatechPointage.spec
```

The portable build is created in:

```text
dist\MecatechPointage\
```

To create the installer locally, install Inno Setup and run:

```powershell
iscc installer.iss
```

## D. Production data and upgrades

Attendance data is stored in the Windows user's Local AppData data directory by default, not in Program Files. The application automatically keeps the newest seven SQLite backups and the Settings page supports manual Backup & Restore.

Before deploying an upgrade to a machine containing real attendance data, create a backup. Never commit a production `attendance.db` to Git.

## E. ESP32 protection

This release does not require an ESP32 firmware update. The existing ESP32-facing API/communication contract remains unchanged; all new attendance, HR, reporting, backup and audit functionality operates locally in the PC application/database layer.
