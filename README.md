# Magazzino – Flask + SQLite

## Installazione
```bash
cd magazzino
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Apri `http://localhost:5000`.

- Admin: `http://localhost:5000/login` (utente: `admin`, password: `admin`).
- Il DB SQLite è salvato in `instance/magazzino.db`.

## Funzioni incluse in questa versione
- Homepage pubblica con tabella filtrabile/ordinabile (DataTables).
- Admin:
  - Aggiunta articolo con **menu a tendina** per categoria, sottotipo, materiale, finitura.
  - Filettature **M / UNC / UNF** con **dropdown** della misura.
  - Selezione opzionale **Ubicazione/Cassettiera** + **Riga/Colonna** per assegnare subito la posizione.
  - **Checkbox** per scegliere i campi da mostrare in etichetta (per articolo).
  - **Modifica** ed **Elimina** articolo.
- API JSON: `/api/items/<id>.json` con posizione (se assegnata).

## Note
- È pre-caricata una Ubicazione “Parete A (PA)” e una Cassettiera “Cassettiera 1 (pair_code AA)”. Puoi crearne altre in una versione successiva.
- Le colonne accettano **A..Z** e **AA..ZZ**; righe 1..128.
- Uno **slot** può contenere più articoli **della stessa categoria** (viene usato il primo scomparto libero).
