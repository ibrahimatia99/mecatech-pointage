import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontendProductionTests(unittest.TestCase):
    def test_dashboard_navigation_and_reliable_settings_save(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(r"\\n", html)
        for tab in ("dashboard", "workers", "leave", "settings"):
            self.assertIn(f"showTab('{tab}', this)", html)
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertEqual(len(scripts), 1)
        script = scripts[0]
        self.assertIn("function showTab(tab, navElement)", script)
        self.assertIn("safeStorageGet", script)
        self.assertIn("safeStorageSet", script)
        self.assertIn('action="/api/settings/update"', html)
        self.assertIn('type="submit" id="settings-save-btn"', html)
        self.assertNotIn('onclick="saveSettings()', html)
        self.assertIn("settings-save-toast", html)
        self.assertIn("apiFetchWithTimeout('/api/settings/update-fast'", script)
        self.assertIn("settingsForm.addEventListener('submit', saveSettingsForm)", script)
        self.assertIn("/api/settings/upload-assets", script)

    def test_report_has_pdf_and_attendance_log_controls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "dashboard" / "report.html").read_text(encoding="utf-8")
        self.assertIn("function openPdfPreview", html)
        self.assertIn("Attendance Log", html)
        self.assertIn("function openEditLogModal", html)
        self.assertIn("function deleteLogDirect", html)
        self.assertNotIn("Download Excel", html)
        self.assertNotIn("Download CSV", html)
        self.assertNotIn("format=xlsx", html)
        self.assertNotIn("format=csv", html)

    def test_all_embedded_page_javascript_is_syntax_valid(self):
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        for rel in (
            "templates/dashboard/index.html",
            "templates/dashboard/report.html",
            "templates/dashboard/pdf_preview.html",
            "templates/auth/login.html",
        ):
            html = (root / rel).read_text(encoding="utf-8")
            scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
            for idx, script in enumerate(scripts):
                script = re.sub(r"\{\{.*?\}\}", "0", script, flags=re.S)
                script = re.sub(r"\{%.*?%\}", "", script, flags=re.S)
                with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tmp:
                    tmp.write(script)
                    path = tmp.name
                try:
                    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, f"{rel} script {idx}: {result.stderr}")
                finally:
                    Path(path).unlink(missing_ok=True)

    def test_light_theme_only_and_no_dark_mode_controls(self):
        root = Path(__file__).resolve().parents[1]
        combined = "\n".join([
            (root/"templates/base.html").read_text(),
            (root/"templates/dashboard/index.html").read_text(),
            (root/"templates/dashboard/report.html").read_text(),
            (root/"templates/dashboard/sections/settings_look.html").read_text(),
            (root/"static/css/style.css").read_text(),
        ]).lower()
        for token in ('data-theme="dark"', 'theme-btn', 'theme-select', 'settheme', 'app_theme'):
            self.assertNotIn(token, combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ProductionGuiAssertions(unittest.TestCase):
    def test_primary_color_is_not_hardcoded_after_config(self):
        css = (ROOT / 'static/css/style.css').read_text(encoding='utf-8')
        self.assertNotIn('--primary: #d93677;', css)
    def test_log_editor_does_not_offer_action_change(self):
        html = (ROOT / 'templates/dashboard/report.html').read_text(encoding='utf-8')
        self.assertNotIn('id="edit-log-action-select"', html)
        self.assertNotIn('This correction would create consecutive', html)

    def test_color_setting_uses_configured_css_variable(self):
        css = (ROOT / 'static/css/style.css').read_text(encoding='utf-8')
        html = (ROOT / 'templates/dashboard/index.html').read_text(encoding='utf-8')
        self.assertNotIn('--primary: #d93677;', css)
        self.assertIn('--primary: {{ cfg.primary_color }}', html)
        self.assertIn("syncPrimaryColorFromPicker", html)
        self.assertIn("syncPrimaryColorFromText", html)

