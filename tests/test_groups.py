"""Gestore siti: lo stato aperto/chiuso dei gruppi resta come l'ha lasciato l'utente (ricostruzioni dell'albero,
ricerca, riapertura del Gestore, riavvio del programma). Uso: python tests/test_groups.py"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEV_SITE = os.path.join(ROOT, ".venv", "Lib", "site-packages")
if os.path.isdir(DEV_SITE):
    import site
    site.addsitedir(DEV_SITE)
WORK = tempfile.mkdtemp(prefix="tkftp-gruppi-")
os.environ["TKFTP_DATI"] = WORK
os.environ["TKFTP_VAULT_SERVICE"] = "tk-ftp-collaudo-gruppi"

from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  NO   ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def main():
    app = QApplication(sys.argv)
    from tkftp.sitemanager import SiteManager
    from tkftp.sites import Site, SiteStore
    from tkftp.util import Settings
    st = SiteStore()
    sites = [Site(name="Generico 1", host="g1.it", group="2.Generici"),
             Site(name="Generico 2", host="g2.it", group="2.Generici"),
             Site(name="Cincotti", host="c.it", group="3.Cincotti"),
             Site(name="Cincotti dev", host="cd.it", group="3.Cincotti/Sviluppo"),
             Site(name="Fiorentino", host="f.it", group="4.Fiorentino"),
             Site(name="FastService", host="fs.it", group="5.FastService", last_used=1000.0)]
    for s in sites:
        st.upsert(s, None)
    cfg = Settings()

    def state(dlg):
        return {p: it.isExpanded() for p, it in dlg._groups.items()}

    dlg = SiteManager(None, st, {}, None, settings=cfg)
    dlg.show()
    app.processEvents()
    s0 = state(dlg)
    check(s0["5.FastService"] and not any(v for k, v in s0.items() if k != "5.FastService"),
          f"di default chiusi tranne il gruppo dell'ultimo sito usato: {s0}")
    # l'utente apre Cincotti e il sottogruppo, chiude FastService
    dlg.tree.expandItem(dlg._groups["3.Cincotti"])
    dlg.tree.expandItem(dlg._groups["3.Cincotti/Sviluppo"])
    dlg.tree.collapseItem(dlg._groups["5.FastService"])
    app.processEvents()
    want = {"2.Generici": False, "3.Cincotti": True, "3.Cincotti/Sviluppo": True, "4.Fiorentino": False,
            "5.FastService": False}
    check(state(dlg) == want, "scelte dell'utente applicate")
    # ricostruzione dell'albero (come dopo un salvataggio) e selezione di un sito in un gruppo chiuso
    dlg.rebuild(sites[0].id)
    app.processEvents()
    check(state(dlg) == want, f"dopo la ricostruzione con un sito di un gruppo chiuso selezionato: {state(dlg)}")
    # modifica di un sito con salvataggio automatico
    dlg.rebuild(sites[4].id)  # sito «Fiorentino» (gruppo chiuso) selezionato come fa il programma
    dlg.f_name.setText("Fiorentino srl")
    dlg._changed()
    dlg._flush()
    app.processEvents()
    check(state(dlg) == want, f"dopo il salvataggio automatico: {state(dlg)}")
    # ricerca: aperti i gruppi con risultati, poi si torna allo stato salvato
    dlg.search.setText("generico")
    app.processEvents()
    check(dlg._groups["2.Generici"].isExpanded(), "ricerca: aperto il gruppo con risultati")
    dlg.search.setText("")
    app.processEvents()
    check(state(dlg) == want, f"ricerca svuotata: stato salvato ripristinato {state(dlg)}")
    dlg.close()
    # riapertura del Gestore
    dlg2 = SiteManager(None, st, {}, None, settings=cfg)
    dlg2.show()
    app.processEvents()
    want2 = dict(want, **{"5.FastService": True})  # alla riapertura si apre il gruppo dell'ultimo sito usato
    check(state(dlg2) == want2, f"riapertura del Gestore: {state(dlg2)}")
    dlg2.tree.collapseItem(dlg2._groups["5.FastService"])
    dlg2.close()
    # riavvio: impostazioni rilette dal disco, aperto con un sito di un gruppo chiuso selezionato
    cfg2 = Settings()
    dlg3 = SiteManager(None, SiteStore(), {}, sites[2].id, settings=cfg2)
    dlg3.show()
    app.processEvents()
    check(state(dlg3) == dict(want, **{"5.FastService": False}), f"dopo il riavvio: {state(dlg3)}")
    dlg3.close()
    shutil.rmtree(WORK, ignore_errors=True)
    print("GRUPPI OK" if not FAILS else f"GRUPPI FALLITO: {FAILS}", flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
