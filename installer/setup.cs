// Installer generico dei software TK per Windows (modello da tkPDF): estrae il pacchetto incorporato,
// crea i collegamenti e la voce in «App installate». Nessun permesso di amministratore (installazione per utente).
// I segnaposto @@...@@ li sostituisce installer\build.ps1 di ogni software.
//   @@SUBDIR@@   "app" = come il portatile (cartella app\ + cartella dati accanto) · "" = tutto nella cartella (tkPDF, tkTV)
//   @@UNINSTALL@@ "cmd" = Disinstalla.cmd accanto ad app\ · "app" = l'app stessa (run.py --uninstall)
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Installazione @@NAME@@")]
[assembly: AssemblyDescription("Installazione di @@NAME@@ - @@TAGLINE@@")]
[assembly: AssemblyCompany("TecnikGeek")]
[assembly: AssemblyProduct("@@NAME@@")]
[assembly: AssemblyCopyright("TecnikGeek - pietrodefilippis.it")]
[assembly: AssemblyVersion("@@VERSION@@.0")]
[assembly: AssemblyFileVersion("@@VERSION@@.0")]

static class Cfg
{
    public const string Name = "@@NAME@@";
    public const string Slug = "@@SLUG@@";
    public const string Tagline = "@@TAGLINE@@";
    public const string Version = "@@VERSION@@";
    public const int SizeKb = @@SIZEKB@@;
    public const string SubDir = "@@SUBDIR@@";
    public const string DataDir = "@@DATADIR@@";
    public const string IconFile = "@@ICON@@";
    public const string Accent = "@@ACCENT@@";
    public const string Uninstall = "@@UNINSTALL@@";
    public const string UninstallKeyName = "@@UNINSTALLKEY@@";
    public const string Lnk = "@@LNK@@";
    public const string LegacyLnk = "@@LEGACYLNK@@";
    public const string LaunchSchema = "@@LAUNCHSCHEMA@@";
    public const string FlatItems = "@@ITEMS@@";
    public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + UninstallKeyName;
}

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (args.Any(a => a.Equals("/S", StringComparison.OrdinalIgnoreCase) || a == "--silent"))
        {
            string existing = Installer.ExistingDir();
            Installer.Run(existing ?? Installer.DefaultDir, existing == null || File.Exists(Installer.DesktopShortcut), null);
            return;
        }
        Application.Run(new SetupForm(args.Contains("--update")));
    }
}

static class Installer
{
    public static string DefaultDir
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", Cfg.Slug); }
    }

    public static string DesktopShortcut
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Cfg.Lnk + ".lnk"); }
    }

    /// Cartella della versione già installata (dalla voce di disinstallazione), se presente.
    public static string ExistingDir()
    {
        try
        {
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey(Cfg.UninstallKey))
            {
                string v = k == null ? null : k.GetValue("InstallLocation") as string;
                return !string.IsNullOrEmpty(v) && Directory.Exists(v) ? v : null;
            }
        }
        catch { return null; }
    }

    public static string NormalizeDir(string dir)
    {
        dir = Path.GetFullPath(dir.Trim()).TrimEnd('\\');
        // non installare mai "sciolto" in una cartella qualsiasi (es. Documenti)
        if (!string.Equals(Path.GetFileName(dir), Cfg.Slug, StringComparison.OrdinalIgnoreCase))
            dir = Path.Combine(dir, Cfg.Slug);
        return dir;
    }

    /// Cartella che contiene python\, assets\ e run.py.
    public static string AppDir(string dir)
    {
        return Cfg.SubDir.Length == 0 ? dir : Path.Combine(dir, Cfg.SubDir);
    }

    /// Copia di pythonw.exe con il nome dell'app (tkTV) se c'è, altrimenti pythonw.exe: è sempre lo stesso file
    /// già noto a Windows, quindi nessun exe nuovo da far approvare a Smart App Control.
    public static string PythonW(string appDir)
    {
        foreach (string name in new[] { "tk-tv.exe", "pythonw.exe" })
        {
            string p = Path.Combine(appDir, "python", name);
            if (File.Exists(p)) return p;
        }
        return Path.Combine(appDir, "python", "pythonw.exe");
    }

    public static void Run(string dir, bool desktopShortcut, Action<int, string> progress)
    {
        Action<int, string> report = progress ?? new Action<int, string>((p, s) => { });
        string appDir = AppDir(dir);
        report(1, "Chiusura di " + Cfg.Name + " se aperto…");
        KillRunning(dir);

        report(3, "Rimozione della versione precedente…");
        if (Cfg.SubDir.Length > 0)
        {
            if (Directory.Exists(appDir)) Retry(() => Directory.Delete(appDir, true));
        }
        else
        {
            foreach (string sub in Cfg.FlatItems.Split(';'))
            {
                string p = Path.Combine(dir, sub);
                if (sub.Length > 0 && Directory.Exists(p)) Retry(() => Directory.Delete(p, true));
            }
        }
        Directory.CreateDirectory(appDir);
        if (Cfg.DataDir.Length > 0) Directory.CreateDirectory(Path.Combine(dir, Cfg.DataDir));

        string fullDir = Path.GetFullPath(appDir).TrimEnd('\\') + "\\";
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
        {
            int total = zip.Entries.Count, i = 0;
            foreach (ZipArchiveEntry e in zip.Entries)
            {
                string target = Path.GetFullPath(Path.Combine(appDir, e.FullName.Replace('/', '\\')));
                if (!target.StartsWith(fullDir, StringComparison.OrdinalIgnoreCase)) continue;
                if (string.IsNullOrEmpty(e.Name))
                {
                    Directory.CreateDirectory(target);
                }
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    ZipArchiveEntry entry = e;
                    Retry(() => entry.ExtractToFile(target, true));
                }
                i++;
                if (i % 20 == 0 || i == total) report(5 + i * 85 / total, "Copia dei file… " + (i * 100 / total) + "%");
            }
        }

        report(92, "Creazione dei collegamenti…");
        string exe = PythonW(appDir);
        string runArgs = Quote(Path.Combine(appDir, "run.py"));
        string icon = Path.Combine(appDir, "assets", Cfg.IconFile);
        string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (Cfg.LegacyLnk.Length > 0)
        {
            foreach (string folder in new[] { programs, desktop })
            {
                try { File.Delete(Path.Combine(folder, Cfg.LegacyLnk + ".lnk")); } catch { }
            }
        }
        string description = Cfg.Name + " - " + Cfg.Tagline;
        CreateShortcut(Path.Combine(programs, Cfg.Lnk + ".lnk"), exe, runArgs, icon, appDir, description);
        if (desktopShortcut) CreateShortcut(DesktopShortcut, exe, runArgs, icon, appDir, description);

        string uninstallString;
        if (Cfg.Uninstall == "cmd")
        {
            report(95, "Preparazione della disinstallazione…");
            string cmdPath = Path.Combine(dir, "Disinstalla " + Cfg.Name + ".cmd");
            File.WriteAllText(cmdPath, UninstallScript(dir), Encoding.ASCII);
            uninstallString = "cmd.exe /c \"\"" + cmdPath + "\"\"";
        }
        else
        {
            uninstallString = Quote(exe) + " " + runArgs + " --uninstall";
        }

        using (RegistryKey k = Registry.CurrentUser.CreateSubKey(Cfg.UninstallKey))
        {
            k.SetValue("DisplayName", Cfg.Name);
            k.SetValue("DisplayVersion", Cfg.Version);
            k.SetValue("Publisher", "TecnikGeek");
            k.SetValue("DisplayIcon", icon);
            k.SetValue("InstallLocation", dir);
            k.SetValue("UninstallString", uninstallString);
            k.SetValue("URLInfoAbout", "https://pietrodefilippis.it");
            k.SetValue("EstimatedSize", Cfg.SizeKb, RegistryValueKind.DWord);
            k.SetValue("NoModify", 1, RegistryValueKind.DWord);
            k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
            if (Cfg.LaunchSchema.Length > 0) k.SetValue("TkLaunchSchema", Cfg.LaunchSchema);
        }
        report(100, "Installazione completata");
    }

    /// Script di disinstallazione (solo comandi di cmd: niente exe né PowerShell, come gli aggiornamenti delle app).
    /// Si copia in %TEMP% e da lì cancella la cartella; dati e password dell'utente solo se risponde S alla domanda.
    static string UninstallScript(string dir)
    {
        string lnk = Cfg.Lnk + ".lnk";
        var sb = new StringBuilder();
        sb.AppendLine("@echo off");
        sb.AppendLine("rem Disinstalla " + Cfg.Name + ". I tuoi dati (cartella \"" + Cfg.DataDir + "\") e le password si cancellano solo se lo chiedi.");
        sb.AppendLine("set \"ROOT=" + dir + "\"");
        sb.AppendLine("if /i not \"%~dp0\"==\"%TEMP%\\\" (");
        sb.AppendLine("  copy /y \"%~f0\" \"%TEMP%\\tk-disinstalla-" + Cfg.Slug + ".cmd\" >nul");
        sb.AppendLine("  start \"\" \"%TEMP%\\tk-disinstalla-" + Cfg.Slug + ".cmd\"");
        sb.AppendLine("  exit /b 0");
        sb.AppendLine(")");
        sb.AppendLine("title Disinstallazione " + Cfg.Name);
        sb.AppendLine("echo.");
        sb.AppendLine("echo   Disinstallazione di " + Cfg.Name + " in corso...");
        sb.AppendLine("set TENTATIVI=0");
        sb.AppendLine(":riprova");
        sb.AppendLine("if exist \"%ROOT%\\" + Cfg.SubDir + "\" rd /s /q \"%ROOT%\\" + Cfg.SubDir + "\" 2>nul");
        sb.AppendLine("if not exist \"%ROOT%\\" + Cfg.SubDir + "\" goto tolto");
        sb.AppendLine("set /a TENTATIVI+=1");
        sb.AppendLine("if %TENTATIVI% GEQ 3 goto bloccato");
        sb.AppendLine("echo   " + Cfg.Name + " e' ancora aperto: chiudilo, poi premi un tasto per riprovare.");
        sb.AppendLine("pause >nul");
        sb.AppendLine("goto riprova");
        sb.AppendLine(":bloccato");
        sb.AppendLine("echo.");
        sb.AppendLine("echo   Non riesco a rimuovere i file: chiudi " + Cfg.Name + " e ripeti la disinstallazione.");
        sb.AppendLine("pause");
        sb.AppendLine("exit /b 1");
        sb.AppendLine(":tolto");
        sb.AppendLine("del /f /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\" + lnk + "\" 2>nul");
        sb.AppendLine("del /f /q \"%USERPROFILE%\\Desktop\\" + lnk + "\" 2>nul");
        sb.AppendLine("del /f /q \"%ROOT%\\" + lnk + "\" 2>nul");
        sb.AppendLine("reg delete \"HKCU\\" + Cfg.UninstallKey + "\" /f >nul 2>nul");
        sb.AppendLine("del /f /q \"%ROOT%\\Disinstalla " + Cfg.Name + ".cmd\" 2>nul");
        // dati e password: si cancellano solo se l'utente lo chiede (S), altrimenti restano per una nuova installazione
        sb.AppendLine("echo.");
        sb.AppendLine("echo   Vuoi cancellare anche i tuoi dati di " + Cfg.Name + "?");
        sb.AppendLine("echo   - siti, gruppi, impostazioni e chiavi dei server (cartella \"" + Cfg.DataDir + "\")");
        sb.AppendLine("echo   - le password salvate in Gestione credenziali di Windows (voci " + Cfg.Slug + ":...)");
        sb.AppendLine("echo   Se reinstalli " + Cfg.Name + " e vuoi ritrovarli, rispondi N.");
        sb.AppendLine("choice /c SN /n /m \"   Cancello dati e password? [S/N] \"");
        sb.AppendLine("if errorlevel 2 goto tieni");
        sb.AppendLine("for /f \"tokens=1,* delims==\" %%a in ('cmdkey /list ^| findstr /i /c:\"target=" + Cfg.Slug + ":\"') do cmdkey /delete:%%b >nul 2>nul");
        sb.AppendLine("if exist \"%ROOT%\\" + Cfg.DataDir + "\" rd /s /q \"%ROOT%\\" + Cfg.DataDir + "\" 2>nul");
        sb.AppendLine("rd /s /q \"%APPDATA%\\" + Cfg.Slug + "\" 2>nul");
        sb.AppendLine("echo   Dati e password cancellati.");
        sb.AppendLine("timeout /t 3 >nul");
        sb.AppendLine(":tieni");
        sb.AppendLine("rem se la cartella dei dati e' vuota si toglie anche la cartella del programma");
        sb.AppendLine("rd \"%ROOT%\\" + Cfg.DataDir + "\" 2>nul");
        sb.AppendLine("rd \"%ROOT%\" 2>nul");
        sb.AppendLine("if exist \"%ROOT%\\" + Cfg.DataDir + "\" (");
        sb.AppendLine("  echo.");
        sb.AppendLine("  echo   " + Cfg.Name + " e' stato disinstallato. I tuoi dati sono rimasti qui:");
        sb.AppendLine("  echo   %ROOT%\\" + Cfg.DataDir);
        sb.AppendLine("  pause");
        sb.AppendLine(")");
        sb.AppendLine("exit /b 0");
        return sb.ToString();
    }

    static void KillRunning(string dir)
    {
        string prefix = Path.GetFullPath(dir).TrimEnd('\\') + "\\";
        foreach (string name in new[] { "pythonw", "tk-tv" })
        {
            foreach (Process p in Process.GetProcessesByName(name))
            {
                try
                {
                    if (p.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    {
                        p.Kill();
                        p.WaitForExit(4000);
                    }
                }
                catch { }
            }
        }
    }

    static void Retry(Action action)
    {
        for (int i = 0; ; i++)
        {
            try { action(); return; }
            catch (IOException) { if (i >= 5) throw; Thread.Sleep(500); }
            catch (UnauthorizedAccessException) { if (i >= 5) throw; Thread.Sleep(500); }
        }
    }

    public static void LaunchApp(string dir)
    {
        string appDir = AppDir(dir);
        Process.Start(new ProcessStartInfo(PythonW(appDir), Quote(Path.Combine(appDir, "run.py"))) { WorkingDirectory = appDir, UseShellExecute = false });
    }

    static void CreateShortcut(string path, string target, string arguments, string icon, string workdir, string description)
    {
        Type t = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(t);
        object lnk = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
        Type lt = lnk.GetType();
        lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { target });
        lt.InvokeMember("Arguments", BindingFlags.SetProperty, null, lnk, new object[] { arguments });
        lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { workdir });
        lt.InvokeMember("IconLocation", BindingFlags.SetProperty, null, lnk, new object[] { icon + ",0" });
        lt.InvokeMember("Description", BindingFlags.SetProperty, null, lnk, new object[] { description });
        lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
    }

    public static string Quote(string s)
    {
        return "\"" + s.TrimEnd('\\') + "\"";
    }
}

class SetupForm : Form
{
    static readonly Color Navy = ColorTranslator.FromHtml("#0f172a");
    static readonly Color Navy3 = ColorTranslator.FromHtml("#334155");
    static readonly Color Accent = ColorTranslator.FromHtml(Cfg.Accent);
    static readonly Color Gray50 = ColorTranslator.FromHtml("#f8fafc");
    static readonly Color Gray100 = ColorTranslator.FromHtml("#f1f5f9");
    static readonly Color Gray500 = ColorTranslator.FromHtml("#64748b");

    readonly TextBox pathBox = new TextBox();
    readonly CheckBox desktopCheck = new CheckBox();
    readonly CheckBox launchCheck = new CheckBox();
    readonly ProgressBar bar = new ProgressBar();
    readonly Label status = new Label();
    readonly Button installBtn = new Button();
    readonly Button cancelBtn = new Button();
    readonly Button browseBtn = new Button();
    readonly Icon appIcon;
    readonly bool updateMode;
    bool done;
    string installedDir;

    public SetupForm(bool update)
    {
        updateMode = update;
        AutoScaleDimensions = new SizeF(96F, 96F);
        AutoScaleMode = AutoScaleMode.Dpi;
        Text = (update ? "Aggiornamento " : "Installazione ") + Cfg.Name + " " + Cfg.Version;
        Font = new Font("Segoe UI", 9.5F);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(560, 390);
        BackColor = Color.White;
        try { appIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); Icon = appIcon; } catch { }

        var header = new Panel { Dock = DockStyle.Top, Height = 96 };
        header.Paint += PaintHeader;
        Controls.Add(header);

        var lab = new Label { Text = Cfg.Name + " verrà installato in:", Location = new Point(28, 118), AutoSize = true, ForeColor = Navy };
        Controls.Add(lab);
        pathBox.Text = Installer.ExistingDir() ?? Installer.DefaultDir;
        pathBox.Location = new Point(30, 142);
        pathBox.Size = new Size(384, 26);
        Controls.Add(pathBox);
        browseBtn.Text = "Sfoglia…";
        browseBtn.Location = new Point(422, 139);
        browseBtn.Size = new Size(110, 32);
        StyleButton(browseBtn, Gray100, Navy);
        browseBtn.Click += (s, e) =>
        {
            using (var dlg = new FolderBrowserDialog { Description = "Scegli la cartella di installazione" })
                if (dlg.ShowDialog(this) == DialogResult.OK) pathBox.Text = Installer.NormalizeDir(dlg.SelectedPath);
        };
        Controls.Add(browseBtn);

        desktopCheck.Text = "Crea un collegamento sul desktop";
        desktopCheck.Checked = true;
        desktopCheck.Location = new Point(30, 184);
        desktopCheck.AutoSize = true;
        Controls.Add(desktopCheck);
        launchCheck.Text = "Apri " + Cfg.Name + " al termine";
        launchCheck.Checked = true;
        launchCheck.Location = new Point(30, 210);
        launchCheck.AutoSize = true;
        Controls.Add(launchCheck);

        var info = new Label
        {
            Text = "Spazio richiesto: " + (Cfg.SizeKb / 1024) + " MB  ·  Non servono permessi di amministratore",
            Location = new Point(28, 244), AutoSize = true, ForeColor = Gray500
        };
        Controls.Add(info);

        bar.Location = new Point(30, 276);
        bar.Size = new Size(502, 10);
        bar.Visible = false;
        Controls.Add(bar);
        status.Location = new Point(28, 292);
        status.Size = new Size(504, 22);
        status.ForeColor = Gray500;
        Controls.Add(status);

        var footer = new Panel { Dock = DockStyle.Bottom, Height = 62, BackColor = Gray50 };
        Controls.Add(footer);
        var credit = new Label { Text = "Creato da TecnikGeek", AutoSize = true, ForeColor = Gray500, Location = new Point(28, 22) };
        footer.Controls.Add(credit);
        cancelBtn.Text = "Annulla";
        cancelBtn.Size = new Size(100, 36);
        cancelBtn.Location = new Point(310, 13);
        StyleButton(cancelBtn, Gray100, Navy);
        cancelBtn.Click += (s, e) => Close();
        footer.Controls.Add(cancelBtn);
        installBtn.Text = "Installa";
        installBtn.Size = new Size(122, 36);
        installBtn.Location = new Point(418, 13);
        StyleButton(installBtn, Accent, Color.White);
        installBtn.Click += OnInstall;
        footer.Controls.Add(installBtn);
        AcceptButton = installBtn;

        if (update)
        {
            // aggiornamento: stessa cartella e stesse scelte, parte da solo e riapre l'app
            lab.Text = "Aggiornamento di " + Cfg.Name + " alla versione " + Cfg.Version + " in corso…";
            lab.Font = new Font("Segoe UI", 10.5F, FontStyle.Bold);
            desktopCheck.Checked = Installer.ExistingDir() == null || File.Exists(Installer.DesktopShortcut);
            foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, launchCheck, info }) c.Visible = false;
            bar.Location = new Point(30, 160);
            status.Location = new Point(28, 178);
            Shown += (s, e) => OnInstall(this, EventArgs.Empty);
        }
    }

    static void StyleButton(Button b, Color back, Color fore)
    {
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderSize = 0;
        b.BackColor = back;
        b.ForeColor = fore;
        b.Font = new Font("Segoe UI", 9.5F, FontStyle.Bold);
        b.Cursor = Cursors.Hand;
    }

    void PaintHeader(object sender, PaintEventArgs e)
    {
        var panel = (Panel)sender;
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        using (var brush = new LinearGradientBrush(panel.ClientRectangle, Navy, Navy3, 0F))
            g.FillRectangle(brush, panel.ClientRectangle);
        int iconSize = (int)(52 * DeviceDpi / 96.0);
        int left = (int)(28 * DeviceDpi / 96.0);
        if (appIcon != null)
        {
            using (var big = new Icon(appIcon, iconSize, iconSize))
                g.DrawIcon(big, new Rectangle(left, (panel.Height - iconSize) / 2, iconSize, iconSize));
        }
        float tx = left + iconSize + 16 * DeviceDpi / 96f;
        using (var f1 = new Font("Segoe UI", 16F, FontStyle.Bold))
        using (var f2 = new Font("Segoe UI", 9.5F))
        using (var gray = new SolidBrush(ColorTranslator.FromHtml("#cbd5e1")))
        {
            g.DrawString(Cfg.Name, f1, Brushes.White, tx, panel.Height * 0.2f);
            // sottotitolo: su una riga se ci sta, altrimenti va a capo (max 2 righe) e si accorcia con «…», mai tagliato
            string sub = (updateMode ? "Aggiornamento alla versione " : "Installazione versione ") + Cfg.Version + "  ·  " + Cfg.Tagline;
            float width = panel.ClientSize.Width - tx - 2 - 20 * DeviceDpi / 96f;
            bool oneLine = g.MeasureString(sub, f2).Width <= width;
            float top = panel.Height * (oneLine ? 0.56f : 0.50f);
            var box = new RectangleF(tx + 2, top, width, panel.Height - top - 4);
            using (var fmt = new StringFormat { Trimming = StringTrimming.EllipsisWord })
            {
                if (oneLine) fmt.FormatFlags |= StringFormatFlags.NoWrap;
                g.DrawString(sub, f2, gray, box, fmt);
            }
        }
    }

    void OnInstall(object sender, EventArgs e)
    {
        if (done)
        {
            if (launchCheck.Checked && installedDir != null)
            {
                try { Installer.LaunchApp(installedDir); } catch { }
            }
            Close();
            return;
        }
        string dir;
        try { dir = Installer.NormalizeDir(pathBox.Text); }
        catch { MessageBox.Show(this, "Percorso non valido.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
        pathBox.Text = dir;
        foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, installBtn, cancelBtn }) c.Enabled = false;
        bar.Visible = true;
        bool desktop = desktopCheck.Checked;
        var worker = new Thread(() =>
        {
            try
            {
                Installer.Run(dir, desktop, (p, s) => BeginInvoke((Action)(() => { bar.Value = Math.Min(100, p); status.Text = s; })));
                BeginInvoke((Action)(() => Finish(dir)));
            }
            catch (UnauthorizedAccessException)
            {
                BeginInvoke((Action)(() => Fail("Non hai i permessi per scrivere in questa cartella.\nScegli una cartella nel tuo profilo utente.")));
            }
            catch (Exception ex)
            {
                BeginInvoke((Action)(() => Fail("Installazione non riuscita:\n" + ex.Message)));
            }
        });
        worker.IsBackground = true;
        worker.Start();
    }

    void Finish(string dir)
    {
        done = true;
        installedDir = dir;
        status.Text = "✔ " + Cfg.Name + " è installato. Lo trovi nel menu Start" + (desktopCheck.Checked ? " e sul desktop." : ".");
        status.ForeColor = ColorTranslator.FromHtml("#15803d");
        installBtn.Text = "Fine";
        installBtn.Enabled = true;
        installBtn.Focus();
        if (updateMode)
        {
            status.Text = "✔ Aggiornamento completato: riapro " + Cfg.Name + "…";
            var t = new System.Windows.Forms.Timer { Interval = 1200 };
            t.Tick += (s, e) => { t.Stop(); OnInstall(this, EventArgs.Empty); };
            t.Start();
        }
    }

    void Fail(string message)
    {
        MessageBox.Show(this, message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, installBtn, cancelBtn }) c.Enabled = true;
        bar.Visible = false;
        status.Text = "";
    }
}
