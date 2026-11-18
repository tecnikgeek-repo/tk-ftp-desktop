# Crea in dist\: tk-ftp-<ver>-windows.zip (aggiornamento), tk-ftp-<ver>-portatile.zip (cartella da pennetta)
# e tk-ftp-setup-<ver>.exe (installer). Stesso schema di tk-listino: Python incluso, niente exe nuovi a runtime.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$version = (Select-String -Path 'tkftp\__init__.py' -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
$stageRoot = Join-Path $env:TEMP 'tkftp-stage'
$stage = Join-Path $stageRoot 'app'
$dist = Join-Path $root 'dist'
$venv = Join-Path $root '.venv'
Write-Host "== tk-ftp ${version}"
if (Test-Path $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
New-Item -ItemType Directory -Force $dist | Out-Null

function Robo($src, $dst, [string[]]$extra) {
    # /R /W: senza, un file illeggibile fa riprovare robocopy all'infinito e la build resta appesa
    & robocopy $src $dst /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallito ($LASTEXITCODE): $src" }
}

$homeLine = Get-Content "$venv\pyvenv.cfg" | Where-Object { $_ -match '^home\s*=' }
$pyHome = ($homeLine -replace '^home\s*=\s*', '').Trim()
# uv mette una giunzione al posto della cartella: via SSH Windows non la attraversa («punto di montaggio non attendibile»)
$pyTarget = (Get-Item $pyHome).Target
if ($pyTarget) { $pyHome = @($pyTarget)[0] }
# Controllo intelligente delle app di Windows blocca i Python non firmati (es. quelli che scarica uv):
# nel pacchetto va solo il Python ufficiale di python.org, firmato dalla Python Software Foundation
$pyDll = Get-ChildItem $pyHome -File | Where-Object { $_.Name -match '^python3\d+\.dll$' } | Select-Object -First 1
if (-not $pyDll -or (Get-AuthenticodeSignature $pyDll.FullName).Status -ne 'Valid') {
    throw "Il Python del venv ($pyHome) non è firmato: Controllo intelligente delle app lo bloccherebbe. Rifai il venv con il Python ufficiale di python.org: uv venv --python 'C:\Program Files\Python313\python.exe' <venv>"
}
$py = Join-Path $stage 'python'
Robo $pyHome $py @('/XD', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'tcl', 'include', 'libs', 'Scripts',
                   'ensurepip', 'lib2to3', 'site-packages', '__phello__', 'pydoc_data',
                   '/XF', '*.pdb', '_tkinter.pyd', 'tcl*.dll', 'tk*.dll', 'EXTERNALLY-MANAGED')

$sp = "$venv\Lib\site-packages"
$dsp = Join-Path $py 'Lib\site-packages'
New-Item -ItemType Directory -Force $dsp | Out-Null
# librerie: Qt (PySide6 ridotto), paramiko e le sue dipendenze native (cryptography, bcrypt, PyNaCl, cffi), certifi
foreach ($pkg in 'shiboken6', 'certifi', 'paramiko', 'cryptography', 'bcrypt', 'nacl', 'cffi') {
    Robo "$sp\$pkg" "$dsp\$pkg" @('/XD', '__pycache__')
}
Get-ChildItem $sp -Filter '_cffi_backend*.pyd' | Copy-Item -Destination $dsp
Get-ChildItem $sp -Directory | Where-Object { $_.Name -match '^(paramiko|cryptography|bcrypt|pynacl|cffi|certifi)-.*\.dist-info$' } |
    ForEach-Object { Robo $_.FullName "$dsp\$($_.Name)" @() }
$ps = "$sp\PySide6"
$dps = "$dsp\PySide6"
New-Item -ItemType Directory -Force $dps | Out-Null
$files = @('pyside6.abi3.dll', 'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtSvg.pyd', 'Qt6Core.dll', 'Qt6Gui.dll',
           'Qt6Widgets.dll', 'Qt6Svg.dll')  # QtSvg: loghi dei siti in SVG
Get-ChildItem $ps -File | Where-Object {
    $_.Extension -eq '.py' -or $files -contains $_.Name -or $_.Name -match '^(msvcp140|vcruntime140|concrt140)'
} | ForEach-Object { Copy-Item $_.FullName $dps }
foreach ($plug in @('platforms\qwindows.dll', 'styles\qmodernwindowsstyle.dll', 'imageformats\qico.dll',
                    'imageformats\qjpeg.dll', 'imageformats\qgif.dll')) {
    $srcp = Join-Path "$ps\plugins" $plug
    if (Test-Path $srcp) {
        $dstp = Join-Path "$dps\plugins" $plug
        New-Item -ItemType Directory -Force (Split-Path $dstp) | Out-Null
        Copy-Item $srcp $dstp
    }
}
New-Item -ItemType Directory -Force "$dps\translations" | Out-Null
Copy-Item "$ps\translations\qtbase_it.qm" "$dps\translations\" -ErrorAction SilentlyContinue

Robo 'tkftp' "$stage\tkftp" @('/XD', '__pycache__')
Robo 'assets' "$stage\assets" @('/XF', '*.iconset', '*.icns')
Copy-Item 'run.py' $stage

# licenze: AGPL di tk-ftp, elenco dei componenti, testi generici e i file di licenza ORIGINALI dei pacchetti inclusi
# (dai *.dist-info, rinominati «<pacchetto>-<file>.txt») + la licenza di Python (con OpenSSL, libffi…)
$lic = Join-Path $stage 'licenze'
Robo 'licenze' $lic @()
Get-ChildItem $dsp -Directory -Filter '*.dist-info' | ForEach-Object {
    $pkg = ($_.Name -replace '-[0-9].*$', '')
    Get-ChildItem $_.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICEN[CS]E|COPYING|NOTICE)' } | ForEach-Object {
        $n = (($_.Name -replace '\.txt$', '') -replace '\.', '-')   # LICENSE.APACHE → LICENSE-APACHE
        Copy-Item $_.FullName (Join-Path $lic "$pkg-$n.txt")
    }
}
Copy-Item (Join-Path $pyHome 'LICENSE.txt') (Join-Path $lic 'Python-LICENSE.txt')
foreach ($need in 'COPYING-AGPL-3.0.txt', 'COMPONENTI.txt', 'LGPL-3.0.txt', 'paramiko-LICENSE.txt', 'Python-LICENSE.txt') {
    if (-not (Test-Path (Join-Path $lic $need))) { throw "Manca licenze\$need nel pacchetto" }
}
& "$py\python.exe" -m compileall -q "$py\Lib" 2>$null | Out-Null
# il codice di tk-ftp va nel pacchetto SOLO compilato: .pyc accanto ai moduli (-b), sorgenti tolti
& "$py\python.exe" -m compileall -q -b "$stage\tkftp" 2>$null | Out-Null
Get-ChildItem "$stage\tkftp" -Recurse -File -Filter '*.py' | Remove-Item -Force
Get-ChildItem "$stage\tkftp" -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
if (Get-ChildItem "$stage\tkftp" -Recurse -File -Filter '*.py') { throw 'Nel pacchetto sono rimasti dei sorgenti .py' }
Remove-Item "$py\python.exe"

# verifica: avvio reale dal runtime ridotto (finestra + TLS + cifratura + chiavi SSH)
$shot = Join-Path $stageRoot 'selftest.png'
$txt = Join-Path $stageRoot 'selftest.txt'
$p = Start-Process "$py\pythonw.exe" -ArgumentList "`"$stage\run.py`"", '--selftest', "`"$shot`"" -PassThru
if (-not $p.WaitForExit(90000)) { Stop-Process -Id $p.Id -Force; throw 'Selftest in timeout' }
$res = if (Test-Path $txt) { Get-Content $txt -Raw -Encoding UTF8 } else { '' }
if (-not (Test-Path $shot) -or $res -notmatch '^OK') { throw "Selftest fallito: il runtime ridotto non avvia tk-ftp ($res)" }
Copy-Item $shot (Join-Path $dist "selftest-windows.png") -Force
Remove-Item $shot, $txt
Write-Host "   selftest runtime OK ($res)"
if (Test-Path "$stage\Dati") { Remove-Item -LiteralPath "$stage\Dati" -Recurse -Force }

$zipCode = "import os,sys,zipfile`nsrc,dst=sys.argv[1],sys.argv[2]`nwith zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:`n  for d,_,fs in os.walk(src):`n    for f in fs:`n      p=os.path.join(d,f); z.write(p, os.path.relpath(p,src).replace(os.sep,'/'))"
$updateZip = Join-Path $dist "tk-ftp-$version-windows.zip"
& "$pyHome\python.exe" -c $zipCode $stage $updateZip
if ($LASTEXITCODE -ne 0) { throw 'ZIP aggiornamento fallito' }

$pack = Join-Path $stageRoot "pack\tk-ftp-$version"
New-Item -ItemType Directory -Force "$pack\Dati" | Out-Null
Robo $stage "$pack\app" @()
$cmd = Get-Content "$PSScriptRoot\Avvia tk-ftp.cmd" -Raw
[IO.File]::WriteAllText("$pack\Avvia tk-ftp.cmd", ($cmd -replace "`r?`n", "`r`n"), [Text.Encoding]::ASCII)
$readme = Get-Content "$PSScriptRoot\Leggimi.txt" -Raw -Encoding UTF8
[IO.File]::WriteAllText("$pack\Leggimi.txt", ($readme -replace "`r?`n", "`r`n"), (New-Object Text.UTF8Encoding($true)))
# la cartella Dati vuota non entrerebbe nello ZIP: un segnaposto la tiene
[IO.File]::WriteAllText("$pack\Dati\Leggimi.txt", "Qui tk-ftp tiene siti, impostazioni e chiavi dei server. Le password NON stanno qui: sono in Gestione credenziali di Windows.`r`n", (New-Object Text.UTF8Encoding($true)))
$portZip = Join-Path $dist "tk-ftp-$version-portatile.zip"
& "$pyHome\python.exe" -c $zipCode (Join-Path $stageRoot 'pack') $portZip
if ($LASTEXITCODE -ne 0) { throw 'ZIP portatile fallito' }

$sizeKb = [int]((Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$map = [ordered]@{
    NAME = 'tk-ftp'
    SLUG = 'tk-ftp'
    TAGLINE = $(if ($env:TKFTP_TAGLINE) { $env:TKFTP_TAGLINE } else { 'client FTP, FTPS e SFTP' })  # TKFTP_TAGLINE solo per provare il testo lungo
    SUBDIR = 'app'
    DATADIR = 'Dati'
    ICON = 'tk-ftp.ico'
    ACCENT = '#e39a2e'
    UNINSTALL = 'cmd'
    UNINSTALLKEY = 'tk-ftp'
    LNK = 'tk-ftp'
    LEGACYLNK = ''
    LAUNCHSCHEMA = ''
    ITEMS = ''
    VERSION = $version
    SIZEKB = "$sizeKb"
}
# --- ZIP di installazione: niente setup.exe, Controllo intelligente delle app di Windows lo blocca (exe nuovo e non
#     firmato). Installa tk_installa.py col pythonw.exe del pacchetto, firmato. Impostazioni prese da $map.
$cfgInstalla = @{ versione = $version; nome = $map.NAME; slug = $map.SLUG; motto = [string]$map.TAGLINE; accento = $map.ACCENT
    icona = $map.ICON; dati = $map.DATADIR; collegamento = $map.LNK; collegamento_vecchio = $map.LEGACYLNK; chiave = $map.UNINSTALLKEY }
foreach ($k in @{ REGKEYS = 'chiavi_registro'; REGAPPS = 'app_registrate'; EXTRADATA = 'dati_extra' }.GetEnumerator()) {
    if ($map.Contains($k.Key) -and $map[$k.Key]) { $cfgInstalla[$k.Value] = @(([string]$map[$k.Key]).Split(';') | Where-Object { $_ }) }
}
# disinstallazione: chiede se cancellare dati e password (Gestione credenziali, voci tk-ftp:...)
$cfgInstalla.chiedi_dati = $true; $cfgInstalla.credenziali = 'tk-ftp:'; $cfgInstalla.dati_extra = @('%APPDATA%\tk-ftp')
$installZip = & "$env:USERPROFILE\Dropbox\CLAUDE\tk-software\librerie\tk_zip_installa.ps1" -Stage $stage -Dist $dist -PyHome $pyHome -Cfg $cfgInstalla

$sha = (Get-FileHash $updateZip -Algorithm SHA256).Hash.ToLower()
Write-Host "== Creati:`n   $portZip ($([math]::Round((Get-Item $portZip).Length/1MB,1)) MB)`n   $updateZip`n   sha256 aggiornamento: $sha"
Remove-Item -LiteralPath $stageRoot -Recurse -Force
