# tk-ftp

Client FTP, FTPS e SFTP a due pannelli (computer e server) con coda dei trasferimenti in parallelo, ripresa dei
file interrotti, modifica al volo dei file del server, gestore siti con gruppi e importazione/esportazione dei
siti di FileZilla. Le password stanno in Gestione credenziali di Windows o nel Portachiavi del Mac, mai in
chiaro su disco.

**Piattaforme:** Windows 10/11 e macOS (Apple Silicon e Intel).

## Licenza

tk-ftp è software libero: puoi usarlo, studiarlo, modificarlo e ridistribuirlo secondo la
[GNU Affero General Public License v3.0](COPYING) o successiva. È fornito senza alcuna garanzia.
I componenti inclusi nei pacchetti (Python, Qt/PySide6, paramiko, cryptography…) hanno le loro licenze:
vedi [licenze/COMPONENTI.txt](licenze/COMPONENTI.txt).

Il nome tk-ftp e il logo non sono coperti dalla licenza (AGPL sez. 7): una versione modificata deve avere un
nome diverso.

## Avviarlo da sorgente

Serve Python 3.11 o più recente.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      (Mac: .venv/bin/pip install -r requirements.txt)
.venv\Scripts\python run.py                        (Mac: .venv/bin/python run.py)
```

Collaudi (server FTP, FTPS e SFTP di prova in locale, nessuna rete esterna):

```
python tests/test_core.py
python tests/test_sicurezza.py
```

Pacchetti: `installer\build.ps1` (Windows: installer, versione portatile e pacchetto di aggiornamento) e
`mac/build_mac.sh` (macOS: dmg).

## Cosa va in rete

Solo i server che scegli tu; in più la ricerca degli aggiornamenti su pietrodefilippis.it (firmati), il logo dei
siti dal loro sito web (se l'opzione è accesa) e, solo se lo consenti, un segnale anonimo al giorno per contare
le installazioni.
